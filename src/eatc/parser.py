"""Парсер EATLang — рекурсивный спуск по EBNF из SPEC.md §4.

Глубина рекурсии ограничена пределами из limits.py: парсер сам следует
правилам, которые язык навязывает программам.
"""

from dataclasses import fields

from . import ast_nodes as ast
from .errors import CapacityError, EatError
from .limits import (
    MAX_BLOCK_DEPTH,
    MAX_EXPR_DEPTH,
    MAX_PARAMS,
)
from .lexer import Lexer
from .tokens import T, Token

_CMP_OPS = {
    T.EQ: "==",
    T.NE: "!=",
    T.LT: "<",
    T.LE: "<=",
    T.GT: ">",
    T.GE: ">=",
}
_ADD_OPS = {T.PLUS: "+", T.MINUS: "-"}
_MUL_OPS = {T.STAR: "*", T.SLASH: "/", T.PERCENT: "%"}


class Parser:
    def __init__(self, tokens: list[Token], filename: str):
        self.tokens = tokens
        self.filename = filename
        self.pos = 0
        self.expr_depth = 0
        self.block_depth = 0
        # struct-литерал `Name { ... }` запрещён в заголовках if/for/match,
        # где `{` открывает блок
        self.allow_struct_lit = True

    # --- инфраструктура ---------------------------------------------------

    def peek(self, offset: int = 0) -> Token:
        i = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[i]

    def at(self, type_: T) -> bool:
        return self.peek().type == type_

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type != T.EOF:
            self.pos += 1
        return tok

    def accept(self, type_: T) -> Token | None:
        if self.at(type_):
            return self.advance()
        return None

    def expect(self, type_: T, what: str) -> Token:
        if not self.at(type_):
            tok = self.peek()
            raise self.error(f"ожидалось {what}, найдено {tok.value!r}", tok)
        return self.advance()

    def error(self, message: str, tok: Token | None = None) -> EatError:
        tok = tok or self.peek()
        return EatError(self.filename, tok.line, tok.col, message)

    def skip_newlines(self) -> None:
        while self.at(T.NEWLINE):
            self.advance()

    def end_of_stmt(self) -> None:
        if self.at(T.RBRACE) or self.at(T.EOF):
            return
        self.expect(T.NEWLINE, "конец строки (одна инструкция — одна строка)")
        self.skip_newlines()

    # --- программа ---------------------------------------------------------

    def parse_program(self) -> ast.Program:
        first = self.peek()
        program = ast.Program(first.line, first.col, [])
        self.skip_newlines()
        while not self.at(T.EOF):
            program.decls.append(self.parse_top_decl())
            self.skip_newlines()
        return program

    def parse_top_decl(self) -> ast.Node:
        tok = self.peek()
        if tok.type == T.FUNC:
            return self.parse_func()
        if tok.type == T.STRUCT:
            return self.parse_struct()
        if tok.type == T.ENUM:
            return self.parse_enum()
        if tok.type == T.CONST:
            return self.parse_const()
        if tok.type == T.TEST:
            return self.parse_test()
        raise self.error(
            "на верхнем уровне допустимы только func, struct, enum, "
            "const, test (правило 6: мутабельных глобалов нет)"
        )

    def parse_const(self) -> ast.ConstDecl:
        tok = self.expect(T.CONST, "const")
        name = self.expect(T.IDENT, "имя константы")
        self.expect(T.COLON, "':'")
        type_ = self.parse_type()
        self.expect(T.ASSIGN, "'='")
        value = self.parse_expr()
        self.end_of_stmt()
        return ast.ConstDecl(tok.line, tok.col, name.value, type_, value)

    def parse_enum(self) -> ast.EnumDecl:
        tok = self.expect(T.ENUM, "enum")
        name = self.expect(T.IDENT, "имя enum")
        self.expect(T.LBRACE, "'{'")
        self.skip_newlines()
        variants: list[tuple] = []  # (имя, узел типа нагрузки | None)
        while not self.at(T.RBRACE):
            vname = self.expect(T.IDENT, "вариант enum").value
            payload = None
            if self.accept(T.LPAREN):
                payload = self.parse_type()
                self.expect(T.RPAREN, "')'")
            variants.append((vname, payload))
            self.skip_newlines()
            if self.accept(T.COMMA):
                self.skip_newlines()
        self.expect(T.RBRACE, "'}'")
        if not variants:
            raise self.error(f"enum {name.value} не имеет вариантов", tok)
        return ast.EnumDecl(tok.line, tok.col, name.value, variants)

    def parse_struct(self) -> ast.StructDecl:
        tok = self.expect(T.STRUCT, "struct")
        name = self.expect(T.IDENT, "имя struct")
        self.expect(T.LBRACE, "'{'")
        self.skip_newlines()
        fields: list[ast.FieldDecl] = []
        methods: list[ast.FuncDecl] = []
        while not self.at(T.RBRACE):
            if self.at(T.FUNC):
                methods.append(self.parse_func(in_struct=True))
            else:
                ftok = self.expect(T.IDENT, "имя поля или func")
                self.expect(T.COLON, "':'")
                ftype = self.parse_type()
                fields.append(
                    ast.FieldDecl(ftok.line, ftok.col, ftok.value, ftype)
                )
                self.end_of_stmt()
            self.skip_newlines()
        self.expect(T.RBRACE, "'}'")
        return ast.StructDecl(tok.line, tok.col, name.value, fields, methods)

    def parse_test(self) -> ast.TestBlock:
        tok = self.expect(T.TEST, "test")
        name = self.expect(T.IDENT, "имя теста")
        body = self.parse_block()
        return ast.TestBlock(tok.line, tok.col, name.value, body)

    # --- функции ------------------------------------------------------------

    def parse_func(self, in_struct: bool = False) -> ast.FuncDecl:
        tok = self.expect(T.FUNC, "func")
        name = self.expect(T.IDENT, "имя функции")
        self.expect(T.LPAREN, "'('")
        params = self.parse_params(in_struct)
        self.expect(T.RPAREN, "')'")
        ret = None
        if self.accept(T.ARROW):
            ret = self.parse_type()
        self.skip_newlines()
        requires = None
        if self.accept(T.REQUIRES):
            requires = self.parse_expr()
            self.skip_newlines()
        ensures = None
        if self.accept(T.ENSURES):
            ensures = self.parse_expr()
            self.skip_newlines()
        body = self.parse_block()
        is_method = in_struct and bool(params) and params[0].name == "self"
        return ast.FuncDecl(
            tok.line,
            tok.col,
            name.value,
            params,
            ret,
            requires,
            ensures,
            body,
            is_method,
        )

    def parse_params(self, in_struct: bool) -> list[ast.Param]:
        params: list[ast.Param] = []
        while not self.at(T.RPAREN):
            if len(params) >= MAX_PARAMS:
                raise CapacityError(
                    self.filename,
                    self.peek().line,
                    self.peek().col,
                    "параметров функции",
                    MAX_PARAMS,
                )
            if self.at(T.SELF) or self.at(T.VAR):
                mutable = bool(self.accept(T.VAR))  # var self
                tok = self.expect(T.SELF, "self (var в параметрах — "
                                          "только у self)")
                if not in_struct or params:
                    raise self.error(
                        "self допустим только первым параметром метода struct",
                        tok,
                    )
                params.append(
                    ast.Param(tok.line, tok.col, "self", None, mutable)
                )
            else:
                tok = self.expect(T.IDENT, "имя параметра")
                self.expect(T.COLON, "':'")
                params.append(
                    ast.Param(tok.line, tok.col, tok.value, self.parse_type())
                )
            if not self.accept(T.COMMA):
                break
        return params

    # --- типы ----------------------------------------------------------------

    def parse_const_expr(self) -> ast.Expr:
        # константа в типе: без сравнений, иначе `>` в str<N> съедался бы
        # как оператор
        return self.parse_add()

    def parse_type(self) -> ast.Node:
        tok = self.peek()
        if self.accept(T.LBRACKET):
            elem = self.parse_type()
            self.expect(T.SEMI, "';' (тип массива: [T; N])")
            size = self.parse_const_expr()
            self.expect(T.RBRACKET, "']'")
            return ast.ArrayType(tok.line, tok.col, elem, size)
        name = self.expect(T.IDENT, "имя типа")
        if name.value == "str":
            self.expect(T.LT, "'<' (ёмкость строки: str<N>)")
            capacity = self.parse_const_expr()
            self.expect(T.GT, "'>'")
            return ast.StrType(name.line, name.col, capacity)
        if name.value == "Result":
            self.expect(T.LT, "'<'")
            ok = self.parse_type()
            self.expect(T.COMMA, "','")
            err = self.parse_type()
            self.expect(T.GT, "'>'")
            return ast.ResultType(name.line, name.col, ok, err)
        if name.value == "Option":
            self.expect(T.LT, "'<'")
            inner = self.parse_type()
            self.expect(T.GT, "'>'")
            return ast.OptionType(name.line, name.col, inner)
        return ast.TypeName(name.line, name.col, name.value)

    # --- блоки и инструкции -------------------------------------------

    def parse_block(self) -> ast.Block:
        tok = self.expect(T.LBRACE, "'{'")
        self.block_depth += 1
        if self.block_depth > MAX_BLOCK_DEPTH:
            raise CapacityError(
                self.filename,
                tok.line,
                tok.col,
                "глубина вложенности блоков",
                MAX_BLOCK_DEPTH,
            )
        self.skip_newlines()
        stmts: list[ast.Stmt] = []
        while not self.at(T.RBRACE):
            stmts.append(self.parse_stmt())
            self.skip_newlines()
        self.expect(T.RBRACE, "'}'")
        self.block_depth -= 1
        return ast.Block(tok.line, tok.col, stmts)

    def parse_stmt(self) -> ast.Stmt:
        tok = self.peek()
        if tok.type in (T.LET, T.VAR):
            return self.parse_let()
        if tok.type == T.IF:
            return self.parse_if()
        if tok.type == T.FOR:
            return self.parse_for()
        if tok.type == T.LOOP:
            self.advance()
            return ast.LoopStmt(tok.line, tok.col, self.parse_block())
        if tok.type == T.MATCH:
            return self.parse_match()
        if tok.type == T.RETURN:
            self.advance()
            value = None
            if not self.at(T.NEWLINE) and not self.at(T.RBRACE):
                value = self.parse_expr()
            self.end_of_stmt()
            return ast.ReturnStmt(tok.line, tok.col, value)
        if tok.type == T.BREAK:
            self.advance()
            self.end_of_stmt()
            return ast.BreakStmt(tok.line, tok.col)
        if tok.type == T.ASSERT:
            self.advance()
            cond = self.parse_expr()
            self.end_of_stmt()
            return ast.AssertStmt(tok.line, tok.col, cond)
        if tok.type == T.DISCARD:
            self.advance()
            expr = self.parse_expr()
            if not isinstance(expr, (ast.Call, ast.MethodCall)):
                raise self.error(
                    "discard применим только к вызову функции", tok
                )
            self.end_of_stmt()
            return ast.DiscardStmt(tok.line, tok.col, expr)
        return self.parse_expr_or_assign()

    def parse_let(self) -> ast.LetStmt:
        tok = self.advance()  # let | var
        mutable = tok.type == T.VAR
        name = self.expect(T.IDENT, "имя переменной")
        self.expect(T.COLON, "':' (тип обязателен)")
        type_ = self.parse_type()
        self.expect(T.ASSIGN, "'=' (инициализация обязательна)")
        value = self.parse_expr()
        self.end_of_stmt()
        return ast.LetStmt(
            tok.line, tok.col, name.value, type_, value, mutable
        )

    def parse_if(self) -> ast.IfStmt:
        tok = self.expect(T.IF, "if")
        cond = self.parse_head_expr()
        then = self.parse_block()
        elifs: list[tuple] = []
        els = None
        while True:
            self.skip_newlines()
            if self.accept(T.ELIF):
                elif_cond = self.parse_head_expr()
                elifs.append((elif_cond, self.parse_block()))
                continue
            if self.accept(T.ELSE):
                els = self.parse_block()
            break
        return ast.IfStmt(tok.line, tok.col, cond, then, elifs, els)

    def parse_for(self) -> ast.ForStmt:
        tok = self.expect(T.FOR, "for")
        target = self.expect(T.IDENT, "переменная цикла (или _)").value
        self.expect(T.IN, "in")
        start = self.parse_head_expr()
        if self.accept(T.DOTDOT):
            end = self.parse_head_expr()
            iterable: ast.Expr = ast.RangeExpr(
                start.line, start.col, start, end
            )
        else:
            iterable = start
        body = self.parse_block()
        return ast.ForStmt(tok.line, tok.col, target, iterable, body)

    def parse_match(self) -> ast.MatchStmt:
        tok = self.expect(T.MATCH, "match")
        subject = self.parse_head_expr()
        self.expect(T.LBRACE, "'{'")
        self.skip_newlines()
        arms: list[ast.MatchArm] = []
        while not self.at(T.RBRACE):
            atok = self.expect(T.IDENT, "образец (вариант enum, Ok, Err, ...)")
            binding = None
            if self.accept(T.LPAREN):
                btok = self.advance()
                if btok.type not in (T.IDENT,):
                    raise self.error("ожидалось имя или '_'", btok)
                binding = btok.value
                self.expect(T.RPAREN, "')'")
            body = self.parse_block()
            arms.append(
                ast.MatchArm(atok.line, atok.col, atok.value, binding, body)
            )
            self.skip_newlines()
        self.expect(T.RBRACE, "'}'")
        if not arms:
            raise self.error("match без веток", tok)
        return ast.MatchStmt(tok.line, tok.col, subject, arms)

    def parse_expr_or_assign(self) -> ast.Stmt:
        tok = self.peek()
        expr = self.parse_expr()
        if self.accept(T.ASSIGN):
            if not isinstance(expr, (ast.Name, ast.FieldAccess, ast.Index)):
                raise self.error(
                    "слева от '=' должна быть переменная, поле или элемент",
                    tok,
                )
            value = self.parse_expr()
            self.end_of_stmt()
            return ast.AssignStmt(tok.line, tok.col, expr, value)
        if not isinstance(expr, (ast.Call, ast.MethodCall)):
            raise self.error(
                "выражение-инструкция должно быть вызовом; результат нельзя "
                "отбросить молча (правило 7, используйте discard)",
                tok,
            )
        self.end_of_stmt()
        return ast.ExprStmt(tok.line, tok.col, expr)

    # --- выражения ----------------------------------------------------

    def parse_head_expr(self) -> ast.Expr:
        """Выражение в заголовке if/for/match: `{` открывает блок,
        поэтому struct-литерал здесь запрещён."""
        saved = self.allow_struct_lit
        self.allow_struct_lit = False
        try:
            return self.parse_expr()
        finally:
            self.allow_struct_lit = saved

    def parse_expr(self) -> ast.Expr:
        self.expr_depth += 1
        if self.expr_depth > MAX_EXPR_DEPTH:
            raise CapacityError(
                self.filename,
                self.peek().line,
                self.peek().col,
                "глубина выражения",
                MAX_EXPR_DEPTH,
            )
        try:
            return self.parse_or()
        finally:
            self.expr_depth -= 1

    def parse_or(self) -> ast.Expr:
        left = self.parse_and()
        while self.at(T.OR):
            tok = self.advance()
            right = self.parse_and()
            left = ast.BinOp(tok.line, tok.col, "or", left, right)
        return left

    def parse_and(self) -> ast.Expr:
        left = self.parse_not()
        while self.at(T.AND):
            tok = self.advance()
            right = self.parse_not()
            left = ast.BinOp(tok.line, tok.col, "and", left, right)
        return left

    def parse_not(self) -> ast.Expr:
        if self.at(T.NOT):
            tok = self.advance()
            return ast.UnaryOp(tok.line, tok.col, "not", self.parse_cmp())
        return self.parse_cmp()

    def parse_cmp(self) -> ast.Expr:
        left = self.parse_add()
        if self.peek().type in _CMP_OPS:
            tok = self.advance()
            right = self.parse_add()
            return ast.BinOp(
                tok.line, tok.col, _CMP_OPS[tok.type], left, right
            )
        return left

    def parse_add(self) -> ast.Expr:
        left = self.parse_mul()
        while self.peek().type in _ADD_OPS:
            tok = self.advance()
            right = self.parse_mul()
            left = ast.BinOp(
                tok.line, tok.col, _ADD_OPS[tok.type], left, right
            )
        return left

    def parse_mul(self) -> ast.Expr:
        left = self.parse_unary()
        while self.peek().type in _MUL_OPS:
            tok = self.advance()
            right = self.parse_unary()
            left = ast.BinOp(
                tok.line, tok.col, _MUL_OPS[tok.type], left, right
            )
        return left

    def parse_unary(self) -> ast.Expr:
        if self.at(T.MINUS):
            tok = self.advance()
            operand = self.parse_unary()
            if isinstance(operand, ast.IntLit):
                # отрицательный литерал — одно число: иначе -2147483648
                # (INT_MIN) был бы невыразим
                return ast.IntLit(tok.line, tok.col, -operand.value)
            return ast.UnaryOp(tok.line, tok.col, "-", operand)
        return self.parse_postfix()

    def parse_postfix(self) -> ast.Expr:
        expr = self.parse_primary()
        while True:
            if self.accept(T.DOT):
                name = self.expect(T.IDENT, "имя поля или метода")
                if self.accept(T.LPAREN):
                    args = self.parse_args()
                    self.expect(T.RPAREN, "')'")
                    expr = ast.MethodCall(
                        name.line, name.col, expr, name.value, args
                    )
                else:
                    expr = ast.FieldAccess(
                        name.line, name.col, expr, name.value
                    )
                continue
            if self.at(T.LBRACKET):
                tok = self.advance()
                index = self.parse_expr()
                self.expect(T.RBRACKET, "']'")
                expr = ast.Index(tok.line, tok.col, expr, index)
                continue
            return expr

    def parse_args(self) -> list[ast.Expr]:
        args: list[ast.Expr] = []
        saved = self.allow_struct_lit
        self.allow_struct_lit = True  # внутри скобок `{` не открывает блок
        try:
            while not self.at(T.RPAREN):
                args.append(self.parse_expr())
                if not self.accept(T.COMMA):
                    break
        finally:
            self.allow_struct_lit = saved
        return args

    def parse_primary(self) -> ast.Expr:
        tok = self.peek()
        if tok.type == T.INT:
            self.advance()
            return ast.IntLit(tok.line, tok.col, int(tok.value))
        if tok.type == T.TRUE or tok.type == T.FALSE:
            self.advance()
            return ast.BoolLit(tok.line, tok.col, tok.type == T.TRUE)
        if tok.type == T.CHAR:
            self.advance()
            return ast.CharLit(tok.line, tok.col, tok.value)
        if tok.type == T.STRING:
            self.advance()
            return self.parse_interpolation(tok)
        if tok.type == T.SELF:
            self.advance()
            return ast.SelfExpr(tok.line, tok.col)
        if tok.type == T.LPAREN:
            self.advance()
            saved = self.allow_struct_lit
            self.allow_struct_lit = True
            try:
                expr = self.parse_expr()
            finally:
                self.allow_struct_lit = saved
            self.expect(T.RPAREN, "')'")
            return expr
        if tok.type == T.LBRACKET:
            return self.parse_array_lit()
        if tok.type == T.IDENT:
            self.advance()
            if self.at(T.LPAREN):
                self.advance()
                args = self.parse_args()
                self.expect(T.RPAREN, "')'")
                return ast.Call(tok.line, tok.col, tok.value, args)
            if self.at(T.LBRACE) and self.allow_struct_lit:
                return self.parse_struct_lit(tok)
            return ast.Name(tok.line, tok.col, tok.value)
        raise self.error(f"ожидалось выражение, найдено {tok.value!r}", tok)

    def parse_array_lit(self) -> ast.Expr:
        tok = self.expect(T.LBRACKET, "'['")
        elems: list[ast.Expr] = []
        while not self.at(T.RBRACKET):
            elems.append(self.parse_expr())
            # [значение; N] — литерал заполнения (пулы)
            if len(elems) == 1 and self.accept(T.SEMI):
                count = self.parse_const_expr()
                self.expect(T.RBRACKET, "']'")
                return ast.ArrayFill(tok.line, tok.col, elems[0], count)
            if not self.accept(T.COMMA):
                break
        self.expect(T.RBRACKET, "']'")
        if not elems:
            raise self.error("литерал массива не может быть пустым", tok)
        return ast.ArrayLit(tok.line, tok.col, elems)

    def parse_struct_lit(self, name: Token) -> ast.StructLit:
        self.expect(T.LBRACE, "'{'")
        self.skip_newlines()
        fields: list[tuple] = []
        saved = self.allow_struct_lit
        self.allow_struct_lit = True
        try:
            while not self.at(T.RBRACE):
                ftok = self.expect(T.IDENT, "имя поля")
                self.expect(T.COLON, "':'")
                fields.append((ftok.value, self.parse_expr()))
                self.skip_newlines()
                if self.accept(T.COMMA):
                    self.skip_newlines()
        finally:
            self.allow_struct_lit = saved
        self.expect(T.RBRACE, "'}'")
        return ast.StructLit(name.line, name.col, name.value, fields)

    # --- интерполяция строк -------------------------------------------

    def parse_interpolation(self, tok: Token) -> ast.StrLit:
        text = tok.value
        segments: list = []
        literal: list[str] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "{":
                if i + 1 < len(text) and text[i + 1] == "{":
                    literal.append("{")
                    i += 2
                    continue
                end = text.find("}", i + 1)
                if end == -1:
                    raise self.error(
                        "незакрытая '{' в интерполяции строки", tok
                    )
                if literal:
                    segments.append("".join(literal))
                    literal = []
                inner = text[i + 1 : end]
                segments.append(self._parse_sub_expr(inner, tok))
                i = end + 1
                continue
            if ch == "}":
                if i + 1 < len(text) and text[i + 1] == "}":
                    literal.append("}")
                    i += 2
                    continue
                raise self.error(
                    "одиночная '}' в строке (экранируйте: }})", tok
                )
            literal.append(ch)
            i += 1
        if literal:
            segments.append("".join(literal))
        return ast.StrLit(tok.line, tok.col, segments)

    def _parse_sub_expr(self, source: str, tok: Token) -> ast.Expr:
        if not source.strip():
            raise self.error("пустая интерполяция {} в строке", tok)
        sub_tokens = Lexer(source, self.filename, tok.line, tok.col).tokenize()
        sub = Parser(sub_tokens, self.filename)
        expr = sub.parse_expr()
        sub.skip_newlines()
        if not sub.at(T.EOF):
            raise self.error(f"лишние символы в интерполяции: {source!r}", tok)
        return expr


def parse_file(path: str) -> ast.Program:
    with open(path, encoding="utf-8") as f:
        source = f.read()
    tokens = Lexer(source, path).tokenize()
    return Parser(tokens, path).parse_program()


def _stamp_src(obj, fname: str) -> None:
    """Пометить каждый узел файлом-источником: программа из нескольких
    модулей сохраняет атрибуцию ошибок."""
    if isinstance(obj, ast.Node):
        if getattr(obj, "src_file", None) is None:
            obj.src_file = fname
        for field in fields(obj):
            _stamp_src(getattr(obj, field.name), fname)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _stamp_src(item, fname)


def parse_files(paths: list) -> ast.Program:
    """Модули: программа — упорядоченный список файлов с единым
    глобальным пространством имён (повторы имён ловит тайпчекер).
    Эквивалент для self-host компилятора: cat файлов в stdin."""
    programs = [parse_file(p) for p in paths]
    for prog, p in zip(programs, paths):
        _stamp_src(prog, p)
    decls = [d for prog in programs for d in prog.decls]
    return ast.Program(programs[0].line, programs[0].col, decls)
