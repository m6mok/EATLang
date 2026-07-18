struct RtStr 15:1
  field ln :: u32
  field buf :: [u8; 256]
  method write 21:5 ()
  method print 26:5 ()
  method init 34:5 () var_self
  method append_str 40:5 (o: RtStr) var_self
  method append_char 60:5 (c: char) var_self
  method append_bool 67:5 (b: bool) var_self
  method append_u32 83:5 (v: u32) var_self
  method append_i32 110:5 (v: i32) var_self
  method append_u64 120:5 (v: u64) var_self
  method append_i64 147:5 (v: i64) var_self
  method eq 160:5 (o: RtStr) -> bool
  method read_line 203:5 () var_self -> u32
  method p_lo 240:5 () -> u32
  method p_hi 255:5 () -> u32
  method parse_status 269:5 () -> u32
  method parse_value 315:5 () -> i32
func eprint 348:1 (s: str<256>)
func rt_of 360:1 (a: str<16>) -> RtStr
test rt_append_u32 371:1
test rt_append_i32 382:1
test rt_append_u64 395:1
test rt_append_i64 406:1
test rt_append_misc 423:1
test rt_parse 436:1
module lib/core/Buf.eat 452:1
export same 10:5 :: same
export pool16 11:5 :: pool16
func same 15:1 (a: [u8; 16], n: u32, kw: str<16>) -> bool
func pool16 36:1 (p: [[u8; 65536]; 4], a: u32, l: u32) -> [u8; 16]
test buf_same 49:1
test buf_pool16 60:1
module lib/core/Const.eat 72:1
export NONE 12:5 :: NONE
export U32_MAX 13:5 :: U32_MAX
const NONE 16:1 :: u32 = 4294967295
const U32_MAX 17:1 :: u32 = 4294967295
module lib/fmt/Ascii.eat 18:1
export is_digit 7:5 :: is_digit
export is_alpha 8:5 :: is_alpha
export is_space 9:5 :: is_space
export digit_value 10:5 :: digit_value
func is_digit 13:1 (b: u8) -> bool
func is_alpha 20:1 (b: u8) -> bool
func is_space 29:1 (b: u8) -> bool
func digit_value 34:1 (b: u8) -> u8
test ascii_is_digit 41:1
test ascii_is_alpha 49:1
test ascii_is_space 60:1
test ascii_digit_value 71:1
module lib/fmt/Fmt.eat 76:1
export Dec 10:5 :: Dec
export fmt_u32 11:5 :: fmt_u32
export fmt_u64 12:5 :: fmt_u64
export fmt_i32 13:5 :: fmt_i32
export fmt_is 14:5 :: fmt_is
struct Dec 17:1
  field ln :: u32
  field d :: [u8; 20]
func fmt_u32 22:1 (n: u32) -> Dec
func fmt_u64 46:1 (n: u64) -> Dec
func fmt_i32 72:1 (n: i32) -> Dec
func fmt_is 91:1 (t: Dec, kw: str<32>) -> bool
test fmt_u32_digits 108:1
test fmt_u64_digits 115:1
test fmt_i32_digits 121:1
module lib/fmt/Hex.eat 128:1
export hex_digit 6:5 :: hex_digit
export write_hex8 7:5 :: write_hex8
export write_hex16 8:5 :: write_hex16
export hex_val 9:5 :: hex_val
func hex_digit 12:1 (v: u32) -> char
func write_hex8 21:1 (v: u32)
func write_hex16 27:1 (v: u32)
func hex_val 35:1 (b: u8) -> u32
test hex_hex_digit 50:1
test hex_hex_val 57:1
test hex_roundtrip 70:1
module lib/core/U128.eat 75:1
export U128 26:5 :: U128
export U128DivRem 27:5 :: U128DivRem
export I128 28:5 :: I128
export I128DivRem 29:5 :: I128DivRem
export u128 30:5 :: u128
export u128_hi_lo 31:5 :: u128_hi_lo
export mul_64 32:5 :: mul_64
export i128 33:5 :: i128
export i128_make 34:5 :: i128_make
import hex_digit 38:5 :: lib/fmt/Hex.eat hex_digit
struct U128 41:1
  field w0 :: u64
  field w1 :: u64
  field w2 :: u64
  field w3 :: u64
  method lo64 48:5 () -> u64
  method hi64 56:5 () -> u64
  method is_zero 63:5 () -> bool
  method eq 68:5 (o: U128) -> bool
  method lt 73:5 (o: U128) -> bool
  method le 87:5 (o: U128) -> bool
  method add 93:5 (o: U128) -> U128
  method add_wrap 113:5 (o: U128) -> U128
  method sub 134:5 (o: U128) -> U128
  method sub_wrap 158:5 (o: U128) -> U128
  method shl 181:5 (k: u32) -> U128
  method shl_wrap 210:5 (k: u32) -> U128
  method shr 237:5 (k: u32) -> U128
  method mul 418:5 (o: U128) -> U128
  method mul_wrap 463:5 (o: U128) -> U128
  method divrem 504:5 (o: U128) -> U128DivRem
  method divrem_64 527:5 (d: u64) -> U128DivRem
  method divrem_wide 549:5 (o: U128) -> U128DivRem
  method divrem_32 592:5 (d: u64) -> U128DivRem
  method div 618:5 (o: U128) -> U128
  method rem 630:5 (o: U128) -> U128
  method repr_hex 645:5 () -> str<32>
  method repr_dec 673:5 () -> str<40>
func u128 265:1 (lo: u64) -> U128
func u128_hi_lo 273:1 (hi: u64, lo: u64) -> U128
func mul_64 284:1 (a: u64, b: u64) -> U128
struct U128DivRem 306:1
  field q :: U128
  field r :: U128
struct Qr64 312:1
  field q :: u64
  field r :: u64
func clz64 319:1 (x: u64) -> u64
func div_step 358:1 (pre: u64, nxt: u64, dn: u64) -> Qr64
func divlu 393:1 (u1: u64, u0: u64, d: u64) -> Qr64
struct I128 703:1
  field sgn :: bool
  field mag :: U128
  method is_zero 735:5 () -> bool
  method eq 740:5 (o: I128) -> bool
  method lt 745:5 (o: I128) -> bool
  method le 759:5 (o: I128) -> bool
  method neg 764:5 () -> I128
  method abs 773:5 () -> I128
  method add 783:5 (o: I128) -> I128
  method sub 800:5 (o: I128) -> I128
  method mul 812:5 (o: I128) -> I128
  method to_i64 824:5 () -> i64
  method repr_dec 836:5 () -> str<40>
  method divrem 857:5 (o: I128) -> I128DivRem
  method div 874:5 (o: I128) -> I128
  method rem 886:5 (o: I128) -> I128
func i128_make 709:1 (sgn: bool, mag: U128) -> I128
func i128 723:1 (v: i64) -> I128
struct I128DivRem 848:1
  field q :: I128
  field r :: I128
test u128_ctor_edges 899:1
test u128_add_sub_edges 914:1
test u128_cmp 929:1
test u128_mul64_edges 944:1
test u128_mul_edges 954:1
test u128_shifts 969:1
test u128_divrem 985:1
test u128_divrem_64 1007:1
test u128_div_paths 1033:1
test u128_repr 1055:1
test i128_basics 1069:1
test i128_arith 1086:1
test i128_cmp 1101:1
test i128_divrem 1113:1
test i128_repr 1125:1
module lib/fmt/Fixed.eat 1132:1
export Q16 26:5 :: Q16
export Q16_SCALE 27:5 :: Q16_SCALE
export q16 28:5 :: q16
export q16_ratio 29:5 :: q16_ratio
export Q32 30:5 :: Q32
export Q32_SCALE 31:5 :: Q32_SCALE
export q32 32:5 :: q32
export q32_ratio 33:5 :: q32_ratio
import Dec 37:5 :: lib/fmt/Fmt.eat Dec
import fmt_u32 38:5 :: lib/fmt/Fmt.eat fmt_u32
import I128 42:5 :: lib/core/U128.eat I128
import i128 43:5 :: lib/core/U128.eat i128
import i128_make 44:5 :: lib/core/U128.eat i128_make
const Q16_SCALE 47:1 :: i32 = 65536
const Q32_SCALE 48:1 :: i64 = 4294967296
struct Q16 50:1
  field v :: i32
  method add 53:5 (o: Q16) -> Q16
  method sub 58:5 (o: Q16) -> Q16
  method neg 63:5 () -> Q16
  method mul 68:5 (o: Q16) -> Q16
  method div 73:5 (o: Q16) -> Q16
  method eq 79:5 (o: Q16) -> bool
  method lt 84:5 (o: Q16) -> bool
  method le 89:5 (o: Q16) -> bool
  method abs 94:5 () -> Q16
  method min 103:5 (o: Q16) -> Q16
  method max 112:5 (o: Q16) -> Q16
  method clamp 121:5 (lo: Q16, hi: Q16) -> Q16
  method to_int 135:5 () -> i32
  method round 142:5 () -> i32
  method floor 151:5 () -> Q16
  method ceil 161:5 () -> Q16
  method repr 174:5 (digits: u32) -> str<32>
func q16 214:1 (n: i32) -> Q16
func q16_ratio 222:1 (num: i32, den: i32) -> Q16
test q16_ctor 228:1
test q16_arith 241:1
test q16_cmp_util 257:1
test q16_round 277:1
test q16_repr 296:1
struct Q32 313:1
  field v :: i64
  method add 316:5 (o: Q32) -> Q32
  method sub 321:5 (o: Q32) -> Q32
  method neg 326:5 () -> Q32
  method mul 333:5 (o: Q32) -> Q32
  method div 342:5 (o: Q32) -> Q32
  method eq 350:5 (o: Q32) -> bool
  method lt 355:5 (o: Q32) -> bool
  method le 360:5 (o: Q32) -> bool
  method abs 365:5 () -> Q32
  method min 374:5 (o: Q32) -> Q32
  method max 383:5 (o: Q32) -> Q32
  method clamp 392:5 (lo: Q32, hi: Q32) -> Q32
  method to_int 406:5 () -> i32
  method round 414:5 () -> i32
  method floor 423:5 () -> Q32
  method ceil 433:5 () -> Q32
  method repr 445:5 (digits: u32) -> str<32>
func q32 484:1 (n: i32) -> Q32
func q32_ratio 491:1 (num: i64, den: i64) -> Q32
test q32_ctor 499:1
test q32_arith 515:1
test q32_cmp_util 532:1
test q32_round 547:1
test q32_repr 560:1
module lib/fmt/Num.eat 570:1
export min 7:5 :: min
export max 8:5 :: max
export clamp 9:5 :: clamp
func min 12:1 (a: u32, b: u32) -> u32
func max 21:1 (a: u32, b: u32) -> u32
func clamp 30:1 (x: u32, lo: u32, hi: u32) -> u32
test num_min_max 43:1
test num_clamp 54:1
module lib/fmt/Parse.eat 60:1
export parse_i32 8:5 :: parse_i32
func parse_i32 11:1 (s: str<256>) -> Result<i32, ParseError>
test parse_i32_ok 84:1
test parse_i32_err 103:1
module lib/http/Http.eat 135:1
export Header 20:5 :: Header
export Req 21:5 :: Req
export req_new 22:5 :: req_new
export Resp 23:5 :: Resp
export resp_new 24:5 :: resp_new
export Body 25:5 :: Body
export body_new 26:5 :: body_new
export PARSE_MORE 27:5 :: PARSE_MORE
export PARSE_DONE 28:5 :: PARSE_DONE
export HTTP_REQ_CAP 29:5 :: HTTP_REQ_CAP
export HTTP_RESP_CAP 30:5 :: HTTP_RESP_CAP
export HTTP_MAX_HEADERS 31:5 :: HTTP_MAX_HEADERS
export HTTP_MAX_BODY 32:5 :: HTTP_MAX_BODY
export HTTP_NONE 33:5 :: HTTP_NONE
export HTTP_OK 34:5 :: HTTP_OK
export HTTP_CREATED 35:5 :: HTTP_CREATED
export HTTP_NO_CONTENT 36:5 :: HTTP_NO_CONTENT
export HTTP_BAD_REQUEST 37:5 :: HTTP_BAD_REQUEST
export HTTP_NOT_FOUND 38:5 :: HTTP_NOT_FOUND
export HTTP_METHOD_NOT_ALLOWED 39:5 :: HTTP_METHOD_NOT_ALLOWED
export HTTP_PAYLOAD_TOO_LARGE 40:5 :: HTTP_PAYLOAD_TOO_LARGE
export HTTP_HEADERS_TOO_LARGE 41:5 :: HTTP_HEADERS_TOO_LARGE
export HTTP_INSUFFICIENT_STORAGE 42:5 :: HTTP_INSUFFICIENT_STORAGE
import Dec 46:5 :: lib/fmt/Fmt.eat Dec
import fmt_u32 47:5 :: lib/fmt/Fmt.eat fmt_u32
import hex_val 51:5 :: lib/fmt/Hex.eat hex_val
import is_digit 55:5 :: lib/fmt/Ascii.eat is_digit
import digit_value 56:5 :: lib/fmt/Ascii.eat digit_value
const HTTP_REQ_CAP 61:1 :: u32 = 8192
const HTTP_RESP_CAP 62:1 :: u32 = 16384
const HTTP_MAX_HEADERS 63:1 :: u32 = 64
const HTTP_MAX_BODY 65:1 :: u32 = 65536
const PARSE_MORE 67:1 :: u32 = 0
const PARSE_DONE 68:1 :: u32 = 1
const HTTP_NONE 70:1 :: u32 = 4294967295
const HTTP_OK 75:1 :: u32 = 200
const HTTP_CREATED 76:1 :: u32 = 201
const HTTP_NO_CONTENT 77:1 :: u32 = 204
const HTTP_BAD_REQUEST 78:1 :: u32 = 400
const HTTP_NOT_FOUND 79:1 :: u32 = 404
const HTTP_METHOD_NOT_ALLOWED 80:1 :: u32 = 405
const HTTP_PAYLOAD_TOO_LARGE 81:1 :: u32 = 413
const HTTP_HEADERS_TOO_LARGE 82:1 :: u32 = 431
const HTTP_INSUFFICIENT_STORAGE 83:1 :: u32 = 507
func lower 88:1 (b: u8) -> u8
struct Header 97:1
  field ns :: u32
  field nl :: u32
  field vs :: u32
  field vl :: u32
struct Req 106:1
  field raw :: [u8; 8192]
  field n :: u32
  field state :: u32
  field ls :: u32
  field ms :: u32
  field ml :: u32
  field ps :: u32
  field pl :: u32
  field vs :: u32
  field vl :: u32
  field hdr :: [Header; 64]
  field nh :: u32
  field err :: u32
  method push_byte 122:5 (b: u8) var_self -> u32
  method line_end 148:5 (lb: u32, e0: u32) var_self -> u32
  method find_sp 168:5 (b0: u32, e0: u32) var_self -> u32
  method parse_reqline 186:5 (ls2: u32, le: u32) var_self -> u32
  method parse_header 218:5 (ls2: u32, le: u32) var_self -> u32
  method span_is 270:5 (s: u32, l: u32, kw: str<64>) -> bool
  method span_is_ci 288:5 (s: u32, l: u32, kw: str<64>) -> bool
  method method_is 305:5 (m: str<64>) -> bool
  method path_is 310:5 (p: str<64>) -> bool
  method version_is 315:5 (v: str<64>) -> bool
  method find_header 321:5 (name: str<64>) -> u32
  method header_val_is 337:5 (i: u32, v: str<64>) -> bool
  method path_starts 344:5 (pre: str<64>) -> bool
  method path_param 354:5 (skip: u32) -> Option<str<64>>
  method wants_close 372:5 () -> bool
  method span_u32 389:5 (s: u32, l: u32) -> Option<u32>
  method content_length 416:5 () -> Option<u32>
  method is_chunked 427:5 () -> bool
  method reset 442:5 () var_self
  method span_copy 462:5 (s: str<256>, ln: u32) var_self -> bool
  method feed_line 484:5 (s: str<256>) var_self -> u32
  method feed_str 527:5 (s: str<256>) var_self -> u32
func req_new 555:1 () -> Req
struct Body 571:1
  field buf :: [u8; 65536]
  field bn :: u32
  field mode :: u32
  field need :: u32
  field cs :: u32
  field csz :: u32
  field seen :: bool
  field skip :: bool
  field state :: u32
  field err :: u32
  method begin_cl 585:5 (n: u32) var_self
  method begin_chunked 598:5 () var_self
  method store 605:5 (b: u8) var_self -> bool
  method size_end 617:5 () var_self -> u32
  method chunk_size 635:5 (b: u8) var_self -> u32
  method chunk_delim 669:5 (b: u8) var_self -> u32
  method chunk 704:5 (b: u8) var_self -> u32
  method push 726:5 (b: u8) var_self -> u32
  method is_done 751:5 () -> bool
  method at 757:5 (i: u32) -> u8
  method buf_is 764:5 (s: str<64>) -> bool
func body_new 782:1 () -> Body
struct Resp 793:1
  field buf :: [u8; 16384]
  field n :: u32
  field of :: bool
  method put_byte 798:5 (b: u8) var_self
  method put_str 808:5 (s: str<256>) var_self
  method put_dec 818:5 (v: u32) var_self
  method crlf 830:5 () var_self
  method status_line 837:5 (code: u32, text: str<64>) var_self
  method header_line 852:5 (name: str<64>, val: str<128>) var_self
  method body 872:5 (s: str<256>) var_self
  method content_length 883:5 (n: u32) var_self
  method end_headers 891:5 () var_self
func resp_new 897:1 () -> Resp
test http_reqline_ok 902:1
test http_header_ows_ci 919:1
test http_feed_str_batch 935:1
test http_bad_reqline_400 946:1
test http_bad_header_400 956:1
test http_too_many_headers_431 965:1
test http_path_param 975:1
test http_wants_close 1001:1
test http_reset_reuse 1022:1
test http_resp_build 1046:1
test http_content_length 1059:1
test http_body_cl 1088:1
test http_body_cl_413 1112:1
test http_body_chunked 1121:1
test http_body_chunked_400 1161:1
module lib/json/Json.eat 1168:1
export JErr 21:5 :: JErr
export JNode 22:5 :: JNode
export JDoc 23:5 :: JDoc
export JOut 24:5 :: JOut
export json_doc 25:5 :: json_doc
export json_out 26:5 :: json_out
export J_NULL 27:5 :: J_NULL
export J_BOOL 28:5 :: J_BOOL
export J_NUM 29:5 :: J_NUM
export J_STR 30:5 :: J_STR
export J_ARR 31:5 :: J_ARR
export J_OBJ 32:5 :: J_OBJ
import hex_val 36:5 :: lib/fmt/Hex.eat hex_val
import is_digit 40:5 :: lib/fmt/Ascii.eat is_digit
import digit_value 41:5 :: lib/fmt/Ascii.eat digit_value
const JSENT 46:1 :: u32 = 4294967295
const J_NULL 49:1 :: u32 = 0
const J_BOOL 50:1 :: u32 = 1
const J_NUM 51:1 :: u32 = 2
const J_STR 52:1 :: u32 = 3
const J_ARR 53:1 :: u32 = 4
const J_OBJ 54:1 :: u32 = 5
enum JErr 57:1
  variant Capacity
  variant Depth
  variant Input
  variant Syntax
  variant Num
  variant Str
struct JNode 68:1
  field kind :: u32
  field nval :: i64
  field nexp :: i32
  field bval :: bool
  field s_off :: u32
  field s_len :: u32
  field kid :: u32
  field sib :: u32
  field k_off :: u32
  field k_len :: u32
struct JDoc 82:1
  field nodes :: [JNode; 4096]
  field n :: u32
  field arena :: [u8; 65536]
  field a :: u32
  field src :: [u8; 65536]
  field sn :: u32
  field src_over :: bool
  field pos :: u32
  field tnval :: i64
  field tnexp :: i32
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
  method put 120:5 (b: u8) var_self
  method load 131:5 (s: str<256>) var_self
  method clear 142:5 () var_self
  method cb 152:5 () -> u8
  method skip_ws 160:5 () var_self
  method next 174:5 () var_self -> u32
  method lex_str 219:5 () var_self -> u32
  method esc 252:5 () var_self
  method esc_u 280:5 () var_self
  method lex_word 319:5 () var_self -> u32
  method word_is 337:5 (w: str<8>) -> bool
  method lex_num 358:5 () var_self -> u32
  method aput 435:5 (b: u8) var_self
  method alloc 450:5 (k: u32) var_self -> u32
  method value 475:5 (k: u32) var_self -> u32
  method attach 516:5 (id: u32) var_self
  method push 544:5 (id: u32, obj: bool) var_self
  method on_value 563:5 (k: u32) var_self
  method step 582:5 (k: u32) var_self
  method rewind 642:5 () var_self
  method run 657:5 () var_self
  method jerr 687:5 () -> JErr
  method validate 712:5 () var_self -> Result<u32, JErr>
  method parse 726:5 () var_self -> Result<u32, JErr>
  method kind_of 738:5 (id: u32) -> u32
  method is_null 745:5 (id: u32) -> bool
  method as_int 753:5 (id: u32) -> Option<i32>
  method as_i64 769:5 (id: u32) -> Option<i64>
  method num_mant 779:5 (id: u32) -> Option<i64>
  method num_exp 789:5 (id: u32) -> Option<i32>
  method as_bool 798:5 (id: u32) -> Option<bool>
  method count 808:5 (id: u32) -> u32
  method at 824:5 (id: u32, i: u32) -> Option<u32>
  method get 847:5 (id: u32, key: str<256>) -> Option<u32>
  method span_is 872:5 (off: u32, ln: u32, s: str<256>) -> bool
  method key_is 891:5 (id: u32, key: str<256>) -> bool
  method str_is 897:5 (id: u32, s: str<256>) -> bool
  method str_len 906:5 (id: u32) -> u32
  method as_str 915:5 (id: u32) -> Option<str<256>>
struct JOut 944:1
  field n :: u32
  field over :: bool
  field deep :: bool
  field sc :: [u32; 64]
  field scur :: [u32; 64]
  field sd :: u32
  field bkind :: [u32; 64]
  field bcount :: [u32; 64]
  field bd :: u32
  field buf :: [u8; 65536]
  method byte 959:5 (b: u8) var_self
  method word 969:5 (w: str<8>) var_self
  method num 982:5 (mant: i64, exp: i32) var_self
  method uesc 1028:5 (b: u8) var_self
  method eb 1050:5 (b: u8) var_self
  method qstr 1090:5 (d: JDoc, off: u32, ln: u32) var_self
  method open 1105:5 (id: u32, kid: u32) var_self
  method val 1117:5 (d: JDoc, id: u32) var_self
  method walk 1150:5 (d: JDoc) var_self
  method ser 1181:5 (d: JDoc, root: u32) var_self -> Result<u32, JErr>
  method out_is 1205:5 (s: str<256>) -> bool
  method bsep 1232:5 () var_self
  method bopen 1246:5 (kind: u32) var_self
  method begin_array 1257:5 () var_self
  method end_array 1264:5 () var_self
  method begin_obj 1272:5 () var_self
  method end_obj 1279:5 () var_self
  method field 1289:5 (name: str<64>) var_self
  method qval 1312:5 (s: str<256>) var_self
  method bval 1326:5 (b: bool) var_self
  method ival 1337:5 (v: i64) var_self
func json_doc 1345:1 () -> JDoc
func json_out 1360:1 () -> JOut
test json_scalars 1369:1
test json_object 1418:1
test json_escapes 1463:1
test json_errors 1487:1
test json_depth 1562:1
test json_capacity 1587:1
test json_input_overflow 1609:1
test json_validate 1629:1
test json_ser 1648:1
test json_frac_parse 1676:1
test json_frac_roundtrip 1735:1
test json_build 1766:1
module lib/os/Args.eat 1810:1
export get 8:5 :: get
func get 11:1 (i: u32) -> Result<str<256>, IoError>
test get_out_of_range 32:1
module lib/http/Server.eat 38:1
export Server 23:5 :: Server
export Tick 24:5 :: Tick
export server_listen 25:5 :: server_listen
export Bytes 26:5 :: Bytes
export bytes_new 27:5 :: bytes_new
export port_arg 28:5 :: port_arg
export not_found 29:5 :: not_found
export bad_request 30:5 :: bad_request
export too_large 31:5 :: too_large
export too_many_headers 32:5 :: too_many_headers
export method_not_allowed 33:5 :: method_not_allowed
export err_resp 34:5 :: err_resp
export PORT_DEFAULT 35:5 :: PORT_DEFAULT
import Req 39:5 :: lib/http/Http.eat Req
import req_new 40:5 :: lib/http/Http.eat req_new
import Resp 41:5 :: lib/http/Http.eat Resp
import resp_new 42:5 :: lib/http/Http.eat resp_new
import PARSE_MORE 43:5 :: lib/http/Http.eat PARSE_MORE
import PARSE_DONE 44:5 :: lib/http/Http.eat PARSE_DONE
import HTTP_BAD_REQUEST 45:5 :: lib/http/Http.eat HTTP_BAD_REQUEST
import HTTP_NOT_FOUND 46:5 :: lib/http/Http.eat HTTP_NOT_FOUND
import HTTP_METHOD_NOT_ALLOWED 47:5 :: lib/http/Http.eat HTTP_METHOD_NOT_ALLOWED
import HTTP_PAYLOAD_TOO_LARGE 48:5 :: lib/http/Http.eat HTTP_PAYLOAD_TOO_LARGE
import HTTP_HEADERS_TOO_LARGE 49:5 :: lib/http/Http.eat HTTP_HEADERS_TOO_LARGE
import get 53:5 :: lib/os/Args.eat get
import parse_i32 57:5 :: lib/fmt/Parse.eat parse_i32
const PORT_DEFAULT 61:1 :: u32 = 8080
const SRV_NO_CONN 63:1 :: u32 = 4294967295
const SRV_SENT 65:1 :: u32 = 4294967295
const DRAIN_BUDGET 67:1 :: u32 = 8900
const HEAD_BUDGET 70:1 :: u32 = 64
const BODY_BUDGET 71:1 :: u32 = 70000
struct Bytes 76:1
  field buf :: [u8; 65536]
  field n :: u32
  field over :: bool
  method put_byte 83:5 (b: u8) var_self
  method put_str 93:5 (s: str<256>) var_self
  method clear 105:5 () var_self
  method at 112:5 (i: u32) -> u8
func bytes_new 119:1 () -> Bytes
enum Tick 126:1
  variant Idle
  variant Ready
  variant Bad :: u32
struct Server 136:1
  field lst :: u32
  field live :: bool
  field conn :: u32
  field served :: u32
  field req :: Req
  field st :: u32
  field eof :: bool
  field wc :: u32
  method tick 152:5 () var_self -> Tick
  method reply 194:5 (w: Resp) var_self
  method reply_bytes 211:5 (head: Resp, b: Bytes) var_self
  method drop_conn 235:5 () var_self
  method stop 244:5 () var_self
func server_listen 253:1 (port: u16) -> Result<Server, IoError>
func port_arg 270:1 () -> u32
func simple 291:1 (code: u32, text: str<64>, msg: str<256>) -> Resp
func not_found 301:1 () -> Resp
func bad_request 306:1 () -> Resp
func too_large 311:1 () -> Resp
func too_many_headers 316:1 () -> Resp
func method_not_allowed 322:1 () -> Resp
func err_resp 328:1 (st: u32) -> Resp
test server_port_default 339:1
test server_bytes_carrier 346:1
test server_err_resp_codes 359:1
module lib/os/Async.eat 373:1
export Poll 18:5 :: Poll
export ready 19:5 :: ready
export Timer 20:5 :: Timer
export Debounce 21:5 :: Debounce
enum Poll 26:1
  variant Ready
  variant Pending
func ready 33:1 (p: Poll) -> bool
struct Timer 45:1
  field next :: u64
  method fire 50:5 (period: u64) var_self -> Option<u64>
struct Debounce 63:1
  field stable :: u8
  field cand :: u8
  field held :: u32
  method sample 70:5 (raw: u8, hold: u32) var_self -> bool
test async_ready 94:1
test async_debounce 105:1
module lib/os/Io.eat 125:1
export read_line 8:5 :: read_line
func read_line 11:1 () -> Result<str<256>, IoError>
module tests/sig/SigProbe.eat 27:1
import is_digit 8:5 :: lib/fmt/Ascii.eat is_digit
import get 12:5 :: lib/os/Args.eat get
import Poll 16:5 :: lib/os/Async.eat Poll
import ready 17:5 :: lib/os/Async.eat ready
import Timer 18:5 :: lib/os/Async.eat Timer
import Debounce 19:5 :: lib/os/Async.eat Debounce
import same 23:5 :: lib/core/Buf.eat same
import NONE 27:5 :: lib/core/Const.eat NONE
import U32_MAX 28:5 :: lib/core/Const.eat U32_MAX
import q16 32:5 :: lib/fmt/Fixed.eat q16
import Dec 36:5 :: lib/fmt/Fmt.eat Dec
import fmt_u32 37:5 :: lib/fmt/Fmt.eat fmt_u32
import hex_digit 41:5 :: lib/fmt/Hex.eat hex_digit
import Req 45:5 :: lib/http/Http.eat Req
import req_new 46:5 :: lib/http/Http.eat req_new
import read_line 50:5 :: lib/os/Io.eat read_line
import JDoc 54:5 :: lib/json/Json.eat JDoc
import json_doc 55:5 :: lib/json/Json.eat json_doc
import min 59:5 :: lib/fmt/Num.eat min
import parse_i32 63:5 :: lib/fmt/Parse.eat parse_i32
import server_listen 67:5 :: lib/http/Server.eat server_listen
import mul_64 71:5 :: lib/core/U128.eat mul_64
func main 74:1 ()
stats funcs=252 structs=20 stmts=1960
