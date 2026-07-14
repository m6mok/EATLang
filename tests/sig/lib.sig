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
module lib/Ascii.eat 459:1
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
func pool16 37:1 (p: [[u8; 65536]; 2], a: u32, l: u32) -> [u8; 16]
test buf_same 51:1
test buf_pool16 62:1
module lib/Const.eat 73:1
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
module lib/Num.eat 29:1
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
import same 12:5 :: lib/Buf.eat same
import NONE 16:5 :: lib/Const.eat NONE
import U32_MAX 17:5 :: lib/Const.eat U32_MAX
import Dec 21:5 :: lib/Fmt.eat Dec
import fmt_u32 22:5 :: lib/Fmt.eat fmt_u32
import hex_digit 26:5 :: lib/Hex.eat hex_digit
import read_line 30:5 :: lib/Io.eat read_line
import min 34:5 :: lib/Num.eat min
import parse_i32 38:5 :: lib/Parse.eat parse_i32
func main 41:1 ()
stats funcs=38 structs=2 stmts=287
