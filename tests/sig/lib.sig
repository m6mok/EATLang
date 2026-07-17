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
module lib/Async.eat 81:1
export Poll 18:5 :: Poll
export ready 19:5 :: ready
export Timer 20:5 :: Timer
export Debounce 21:5 :: Debounce
enum Poll 26:1
  variant Ready
  variant Pending
func ready 33:1 (p: Poll) -> bool
struct Timer 47:1
  field next :: u64
  method fire 52:5 (period: u64) var_self -> Option<u64>
struct Debounce 67:1
  field stable :: u8
  field cand :: u8
  field held :: u32
  method sample 74:5 (raw: u8, hold: u32) var_self -> bool
test async_ready 99:1
test async_debounce 110:1
module lib/Buf.eat 130:1
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
  method value 455:5 (k: u32) var_self -> u32
  method attach 496:5 (id: u32) var_self
  method push 525:5 (id: u32, obj: bool) var_self
  method on_value 545:5 (k: u32) var_self
  method step 564:5 (k: u32) var_self
  method rewind 624:5 () var_self
  method run 640:5 () var_self
  method jerr 671:5 () -> JErr
  method validate 698:5 () var_self -> Result<u32, JErr>
  method parse 714:5 () var_self -> Result<u32, JErr>
  method kind_of 728:5 (id: u32) -> u32
  method is_null 735:5 (id: u32) -> bool
  method as_int 742:5 (id: u32) -> Option<i32>
  method as_bool 752:5 (id: u32) -> Option<bool>
  method count 763:5 (id: u32) -> u32
  method at 780:5 (id: u32, i: u32) -> Option<u32>
  method get 804:5 (id: u32, key: str<256>) -> Option<u32>
  method span_is 830:5 (off: u32, ln: u32, s: str<256>) -> bool
  method key_is 851:5 (id: u32, key: str<256>) -> bool
  method str_is 858:5 (id: u32, s: str<256>) -> bool
  method str_len 868:5 (id: u32) -> u32
  method as_str 878:5 (id: u32) -> Option<str<256>>
struct JOut 908:1
  field n :: u32
  field over :: bool
  field deep :: bool
  field sc :: [u32; 64]
  field scur :: [u32; 64]
  field sd :: u32
  field buf :: [u8; 65536]
  method byte 917:5 (b: u8) var_self
  method word 928:5 (w: str<8>) var_self
  method dec 940:5 (v: i32) var_self
  method uesc 969:5 (b: u8) var_self
  method eb 991:5 (b: u8) var_self
  method qstr 1032:5 (d: JDoc, off: u32, ln: u32) var_self
  method open 1048:5 (id: u32, kid: u32) var_self
  method val 1061:5 (d: JDoc, id: u32) var_self
  method walk 1094:5 (d: JDoc) var_self
  method ser 1126:5 (d: JDoc, root: u32) var_self -> Result<u32, JErr>
  method out_is 1151:5 (s: str<256>) -> bool
func json_doc 1172:1 () -> JDoc
func json_out 1189:1 () -> JOut
test json_scalars 1199:1
test json_object 1248:1
test json_escapes 1293:1
test json_errors 1317:1
test json_depth 1377:1
test json_capacity 1402:1
test json_input_overflow 1424:1
test json_validate 1444:1
test json_ser 1463:1
module lib/Num.eat 1489:1
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
module lib/U128.eat 85:1
export U128 26:5 :: U128
export U128DivRem 27:5 :: U128DivRem
export I128 28:5 :: I128
export I128DivRem 29:5 :: I128DivRem
export u128 30:5 :: u128
export u128_hi_lo 31:5 :: u128_hi_lo
export mul_64 32:5 :: mul_64
export i128 33:5 :: i128
export i128_make 34:5 :: i128_make
import hex_digit 38:5 :: lib/Hex.eat hex_digit
struct U128 41:1
  field w0 :: u64
  field w1 :: u64
  field w2 :: u64
  field w3 :: u64
  method lo64 48:5 () -> u64
  method hi64 57:5 () -> u64
  method is_zero 65:5 () -> bool
  method eq 72:5 (o: U128) -> bool
  method lt 79:5 (o: U128) -> bool
  method le 95:5 (o: U128) -> bool
  method add 103:5 (o: U128) -> U128
  method add_wrap 123:5 (o: U128) -> U128
  method sub 144:5 (o: U128) -> U128
  method sub_wrap 168:5 (o: U128) -> U128
  method shl 191:5 (k: u32) -> U128
  method shl_wrap 220:5 (k: u32) -> U128
  method shr 247:5 (k: u32) -> U128
  method mul 328:5 (o: U128) -> U128
  method mul_wrap 353:5 (o: U128) -> U128
  method divrem 378:5 (o: U128) -> U128DivRem
  method divrem_32 421:5 (d: u64) -> U128DivRem
  method div 447:5 (o: U128) -> U128
  method rem 459:5 (o: U128) -> U128
  method repr_hex 474:5 () -> str<32>
  method repr_dec 503:5 () -> str<40>
func u128 275:1 (lo: u64) -> U128
func u128_hi_lo 284:1 (hi: u64, lo: u64) -> U128
func mul_64 296:1 (a: u64, b: u64) -> U128
struct U128DivRem 319:1
  field q :: U128
  field r :: U128
struct I128 534:1
  field sgn :: bool
  field mag :: U128
  method is_zero 567:5 () -> bool
  method eq 574:5 (o: I128) -> bool
  method lt 581:5 (o: I128) -> bool
  method le 597:5 (o: I128) -> bool
  method neg 604:5 () -> I128
  method abs 613:5 () -> I128
  method add 623:5 (o: I128) -> I128
  method sub 640:5 (o: I128) -> I128
  method mul 652:5 (o: I128) -> I128
  method to_i64 664:5 () -> i64
  method repr_dec 677:5 () -> str<40>
  method divrem 699:5 (o: I128) -> I128DivRem
  method div 716:5 (o: I128) -> I128
  method rem 728:5 (o: I128) -> I128
func i128_make 540:1 (sgn: bool, mag: U128) -> I128
func i128 554:1 (v: i64) -> I128
struct I128DivRem 690:1
  field q :: I128
  field r :: I128
test u128_ctor_edges 741:1
test u128_add_sub_edges 756:1
test u128_cmp 771:1
test u128_mul64_edges 786:1
test u128_mul_edges 796:1
test u128_shifts 808:1
test u128_divrem 824:1
test u128_repr 844:1
test i128_basics 858:1
test i128_arith 875:1
test i128_cmp 890:1
test i128_divrem 902:1
test i128_repr 914:1
module lib/Fixed.eat 921:1
export Q16 26:5 :: Q16
export Q16_SCALE 27:5 :: Q16_SCALE
export q16 28:5 :: q16
export q16_ratio 29:5 :: q16_ratio
export Q32 30:5 :: Q32
export Q32_SCALE 31:5 :: Q32_SCALE
export q32 32:5 :: q32
export q32_ratio 33:5 :: q32_ratio
import Dec 37:5 :: lib/Fmt.eat Dec
import fmt_u32 38:5 :: lib/Fmt.eat fmt_u32
import I128 42:5 :: lib/U128.eat I128
import i128 43:5 :: lib/U128.eat i128
import i128_make 44:5 :: lib/U128.eat i128_make
const Q16_SCALE 47:1 :: i32 = 65536
const Q32_SCALE 48:1 :: i64 = 4294967296
struct Q16 50:1
  field v :: i32
  method add 53:5 (o: Q16) -> Q16
  method sub 60:5 (o: Q16) -> Q16
  method neg 67:5 () -> Q16
  method mul 74:5 (o: Q16) -> Q16
  method div 81:5 (o: Q16) -> Q16
  method eq 88:5 (o: Q16) -> bool
  method lt 95:5 (o: Q16) -> bool
  method le 102:5 (o: Q16) -> bool
  method abs 109:5 () -> Q16
  method min 119:5 (o: Q16) -> Q16
  method max 129:5 (o: Q16) -> Q16
  method clamp 139:5 (lo: Q16, hi: Q16) -> Q16
  method to_int 153:5 () -> i32
  method round 161:5 () -> i32
  method floor 172:5 () -> Q16
  method ceil 184:5 () -> Q16
  method repr 199:5 (digits: u32) -> str<32>
func q16 240:1 (n: i32) -> Q16
func q16_ratio 249:1 (num: i32, den: i32) -> Q16
test q16_ctor 256:1
test q16_arith 269:1
test q16_cmp_util 285:1
test q16_round 305:1
test q16_repr 324:1
struct Q32 341:1
  field v :: i64
  method add 344:5 (o: Q32) -> Q32
  method sub 351:5 (o: Q32) -> Q32
  method neg 358:5 () -> Q32
  method mul 367:5 (o: Q32) -> Q32
  method div 378:5 (o: Q32) -> Q32
  method eq 387:5 (o: Q32) -> bool
  method lt 394:5 (o: Q32) -> bool
  method le 401:5 (o: Q32) -> bool
  method abs 408:5 () -> Q32
  method min 418:5 (o: Q32) -> Q32
  method max 428:5 (o: Q32) -> Q32
  method clamp 438:5 (lo: Q32, hi: Q32) -> Q32
  method to_int 452:5 () -> i32
  method round 461:5 () -> i32
  method floor 472:5 () -> Q32
  method ceil 484:5 () -> Q32
  method repr 498:5 (digits: u32) -> str<32>
func q32 538:1 (n: i32) -> Q32
func q32_ratio 547:1 (num: i64, den: i64) -> Q32
test q32_ctor 556:1
test q32_arith 572:1
test q32_cmp_util 589:1
test q32_round 604:1
test q32_repr 617:1
module tests/sig/SigProbe.eat 627:1
import is_digit 8:5 :: lib/Ascii.eat is_digit
import get 12:5 :: lib/Args.eat get
import Poll 16:5 :: lib/Async.eat Poll
import ready 17:5 :: lib/Async.eat ready
import Timer 18:5 :: lib/Async.eat Timer
import Debounce 19:5 :: lib/Async.eat Debounce
import same 23:5 :: lib/Buf.eat same
import NONE 27:5 :: lib/Const.eat NONE
import U32_MAX 28:5 :: lib/Const.eat U32_MAX
import q16 32:5 :: lib/Fixed.eat q16
import Dec 36:5 :: lib/Fmt.eat Dec
import fmt_u32 37:5 :: lib/Fmt.eat fmt_u32
import hex_digit 41:5 :: lib/Hex.eat hex_digit
import read_line 45:5 :: lib/Io.eat read_line
import JDoc 49:5 :: lib/Json.eat JDoc
import json_doc 50:5 :: lib/Json.eat json_doc
import min 54:5 :: lib/Num.eat min
import parse_i32 58:5 :: lib/Parse.eat parse_i32
import mul_64 62:5 :: lib/U128.eat mul_64
func main 65:1 ()
stats funcs=169 structs=13 stmts=1248
