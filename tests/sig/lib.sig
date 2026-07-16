struct RtStr 15:1
  field ln :: u32
  field buf :: [u8; 256]
  method write 21:5 ()
  method print 28:5 ()
  method init 38:5 () var_self
  method append_str 45:5 (o: RtStr) var_self
  method append_char 67:5 (c: char) var_self
  method append_bool 76:5 (b: bool) var_self
  method append_u32 94:5 (v: u32) var_self
  method append_i32 123:5 (v: i32) var_self
  method append_u64 135:5 (v: u64) var_self
  method append_i64 164:5 (v: i64) var_self
  method eq 179:5 (o: RtStr) -> bool
  method read_line 200:5 () var_self -> u32
  method p_lo 238:5 () -> u32
  method p_hi 254:5 () -> u32
  method parse_status 269:5 () -> u32
  method parse_value 316:5 () -> i32
func eprint 351:1 (s: str<256>)
func rt_of 365:1 (a: str<16>) -> RtStr
test rt_append_u32 378:1
test rt_append_i32 389:1
test rt_append_u64 402:1
test rt_append_i64 413:1
test rt_append_misc 430:1
test rt_parse 443:1
module lib/Args.eat 459:1
export get 8:5 :: get
func get 11:1 (i: u32) -> Result<str<256>, IoError>
test get_out_of_range 34:1
module lib/Ascii.eat 40:1
export is_digit 7:5 :: is_digit
export is_alpha 8:5 :: is_alpha
export is_space 9:5 :: is_space
export digit_value 10:5 :: digit_value
func is_digit 13:1 (b: u8) -> bool
func is_alpha 21:1 (b: u8) -> bool
func is_space 32:1 (b: u8) -> bool
func digit_value 39:1 (b: u8) -> u8
test ascii_is_digit 46:1
test ascii_is_alpha 54:1
test ascii_is_space 65:1
test ascii_digit_value 76:1
module lib/Buf.eat 81:1
export same 10:5 :: same
export pool16 11:5 :: pool16
func same 15:1 (a: [u8; 16], n: u32, kw: str<16>) -> bool
func pool16 37:1 (p: [[u8; 65536]; 4], a: u32, l: u32) -> [u8; 16]
test buf_same 51:1
test buf_pool16 62:1
module lib/Const.eat 74:1
export NONE 12:5 :: NONE
export U32_MAX 13:5 :: U32_MAX
const NONE 16:1 :: u32 = 4294967295
const U32_MAX 17:1 :: u32 = 4294967295
module lib/Fmt.eat 18:1
export Dec 10:5 :: Dec
export fmt_u32 11:5 :: fmt_u32
export fmt_u64 12:5 :: fmt_u64
export fmt_i32 13:5 :: fmt_i32
export fmt_is 14:5 :: fmt_is
struct Dec 17:1
  field ln :: u32
  field d :: [u8; 20]
func fmt_u32 22:1 (n: u32) -> Dec
func fmt_u64 47:1 (n: u64) -> Dec
func fmt_i32 74:1 (n: i32) -> Dec
func fmt_is 94:1 (t: Dec, kw: str<32>) -> bool
test fmt_u32_digits 113:1
test fmt_u64_digits 120:1
test fmt_i32_digits 126:1
module lib/Hex.eat 133:1
export hex_digit 6:5 :: hex_digit
export write_hex8 7:5 :: write_hex8
export write_hex16 8:5 :: write_hex16
export hex_val 9:5 :: hex_val
func hex_digit 12:1 (v: u32) -> char
func write_hex8 22:1 (v: u32)
func write_hex16 29:1 (v: u32)
func hex_val 38:1 (b: u8) -> u32
test hex_hex_digit 54:1
test hex_hex_val 61:1
test hex_roundtrip 74:1
module lib/Io.eat 79:1
export read_line 8:5 :: read_line
func read_line 11:1 () -> Result<str<256>, IoError>
module lib/Json.eat 29:1
export JErr 16:5 :: JErr
export JNode 17:5 :: JNode
export JDoc 18:5 :: JDoc
export JOut 19:5 :: JOut
export json_doc 20:5 :: json_doc
export json_out 21:5 :: json_out
export J_NULL 22:5 :: J_NULL
export J_BOOL 23:5 :: J_BOOL
export J_NUM 24:5 :: J_NUM
export J_STR 25:5 :: J_STR
export J_ARR 26:5 :: J_ARR
export J_OBJ 27:5 :: J_OBJ
import hex_val 31:5 :: lib/Hex.eat hex_val
const JSENT 36:1 :: u32 = 4294967295
const J_NULL 39:1 :: u32 = 0
const J_BOOL 40:1 :: u32 = 1
const J_NUM 41:1 :: u32 = 2
const J_STR 42:1 :: u32 = 3
const J_ARR 43:1 :: u32 = 4
const J_OBJ 44:1 :: u32 = 5
enum JErr 47:1
  variant Capacity
  variant Depth
  variant Input
  variant Syntax
  variant Num
  variant Str
struct JNode 58:1
  field kind :: u32
  field ival :: i32
  field bval :: bool
  field s_off :: u32
  field s_len :: u32
  field kid :: u32
  field sib :: u32
  field k_off :: u32
  field k_len :: u32
struct JDoc 71:1
  field nodes :: [JNode; 4096]
  field n :: u32
  field arena :: [u8; 65536]
  field a :: u32
  field src :: [u8; 65536]
  field sn :: u32
  field src_over :: bool
  field pos :: u32
  field tival :: i32
  field toff :: u32
  field tlen :: u32
  field fc :: [u32; 64]
  field fl :: [u32; 64]
  field fst :: [u32; 64]
  field fko :: [u32; 64]
  field fkl :: [u32; 64]
  field d :: u32
  field root :: u32
  field err :: u32
  field done :: u32
  field dry :: u32
  field tcount :: u32
  method put 108:5 (b: u8) var_self
  method load 120:5 (s: str<256>) var_self
  method clear 132:5 () var_self
  method cb 143:5 () -> u8
  method skip_ws 153:5 () var_self
  method next 168:5 () var_self -> u32
  method lex_str 215:5 () var_self -> u32
  method esc 250:5 () var_self
  method esc_u 279:5 () var_self
  method lex_word 319:5 () var_self -> u32
  method word_is 339:5 (w: str<8>) -> bool
  method lex_num 360:5 () var_self -> u32
  method aput 413:5 (b: u8) var_self
  method alloc 429:5 (k: u32) var_self -> u32
  method value 452:5 (k: u32) var_self -> u32
  method attach 493:5 (id: u32) var_self
  method push 522:5 (id: u32, obj: bool) var_self
  method on_value 542:5 (k: u32) var_self
  method step 561:5 (k: u32) var_self
  method rewind 621:5 () var_self
  method run 637:5 () var_self
  method jerr 668:5 () -> JErr
  method validate 695:5 () var_self -> Result<u32, JErr>
  method parse 711:5 () var_self -> Result<u32, JErr>
  method kind_of 725:5 (id: u32) -> u32
  method is_null 732:5 (id: u32) -> bool
  method as_int 739:5 (id: u32) -> Option<i32>
  method as_bool 749:5 (id: u32) -> Option<bool>
  method count 760:5 (id: u32) -> u32
  method at 777:5 (id: u32, i: u32) -> Option<u32>
  method get 801:5 (id: u32, key: str<256>) -> Option<u32>
  method span_is 827:5 (off: u32, ln: u32, s: str<256>) -> bool
  method key_is 848:5 (id: u32, key: str<256>) -> bool
  method str_is 855:5 (id: u32, s: str<256>) -> bool
  method str_len 865:5 (id: u32) -> u32
  method as_str 875:5 (id: u32) -> Option<str<256>>
struct JOut 905:1
  field n :: u32
  field over :: bool
  field deep :: bool
  field sc :: [u32; 64]
  field scur :: [u32; 64]
  field sd :: u32
  field buf :: [u8; 65536]
  method byte 914:5 (b: u8) var_self
  method word 925:5 (w: str<8>) var_self
  method dec 937:5 (v: i32) var_self
  method uesc 966:5 (b: u8) var_self
  method eb 988:5 (b: u8) var_self
  method qstr 1029:5 (d: JDoc, off: u32, ln: u32) var_self
  method open 1045:5 (id: u32, kid: u32) var_self
  method val 1058:5 (d: JDoc, id: u32) var_self
  method walk 1091:5 (d: JDoc) var_self
  method ser 1123:5 (d: JDoc, root: u32) var_self -> Result<u32, JErr>
  method out_is 1148:5 (s: str<256>) -> bool
func json_doc 1169:1 () -> JDoc
func json_out 1177:1 () -> JOut
test json_scalars 1184:1
test json_object 1233:1
test json_escapes 1278:1
test json_errors 1302:1
test json_depth 1362:1
test json_capacity 1387:1
test json_input_overflow 1409:1
test json_validate 1429:1
test json_ser 1448:1
module lib/Num.eat 1474:1
export min 7:5 :: min
export max 8:5 :: max
export clamp 9:5 :: clamp
func min 12:1 (a: u32, b: u32) -> u32
func max 22:1 (a: u32, b: u32) -> u32
func clamp 32:1 (x: u32, lo: u32, hi: u32) -> u32
test num_min_max 45:1
test num_clamp 56:1
module lib/Parse.eat 62:1
export parse_i32 7:5 :: parse_i32
func parse_i32 10:1 (s: str<256>) -> Result<i32, ParseError>
test parse_i32_ok 34:1
test parse_i32_err 53:1
module tests/sig/SigProbe.eat 85:1
import is_digit 8:5 :: lib/Ascii.eat is_digit
import get 12:5 :: lib/Args.eat get
import same 16:5 :: lib/Buf.eat same
import NONE 20:5 :: lib/Const.eat NONE
import U32_MAX 21:5 :: lib/Const.eat U32_MAX
import Dec 25:5 :: lib/Fmt.eat Dec
import fmt_u32 26:5 :: lib/Fmt.eat fmt_u32
import hex_digit 30:5 :: lib/Hex.eat hex_digit
import read_line 34:5 :: lib/Io.eat read_line
import JDoc 38:5 :: lib/Json.eat JDoc
import json_doc 39:5 :: lib/Json.eat json_doc
import min 43:5 :: lib/Num.eat min
import parse_i32 47:5 :: lib/Parse.eat parse_i32
func main 50:1 ()
stats funcs=88 structs=5 stmts=842
