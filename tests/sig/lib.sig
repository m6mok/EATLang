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
  method read_line 224:5 () var_self -> u32
  method p_lo 262:5 () -> u32
  method p_hi 278:5 () -> u32
  method parse_status 293:5 () -> u32
  method parse_value 340:5 () -> i32
func eprint 375:1 (s: str<256>)
func rt_of 389:1 (a: str<16>) -> RtStr
test rt_append_u32 402:1
test rt_append_i32 413:1
test rt_append_u64 426:1
test rt_append_i64 437:1
test rt_append_misc 454:1
test rt_parse 467:1
module lib/Args.eat 483:1
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
module lib/Http.eat 79:1
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
import Dec 37:5 :: lib/Fmt.eat Dec
import fmt_u32 38:5 :: lib/Fmt.eat fmt_u32
const HTTP_REQ_CAP 43:1 :: u32 = 8192
const HTTP_RESP_CAP 44:1 :: u32 = 16384
const HTTP_MAX_HEADERS 45:1 :: u32 = 64
const HTTP_MAX_BODY 47:1 :: u32 = 65536
const PARSE_MORE 49:1 :: u32 = 0
const PARSE_DONE 50:1 :: u32 = 1
const HTTP_NONE 52:1 :: u32 = 4294967295
func lower 57:1 (b: u8) -> u8
struct Header 68:1
  field ns :: u32
  field nl :: u32
  field vs :: u32
  field vl :: u32
struct Req 77:1
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
  method push_byte 93:5 (b: u8) var_self -> u32
  method line_end 121:5 (lb: u32, e0: u32) var_self -> u32
  method find_sp 142:5 (b0: u32, e0: u32) var_self -> u32
  method parse_reqline 161:5 (ls2: u32, le: u32) var_self -> u32
  method parse_header 194:5 (ls2: u32, le: u32) var_self -> u32
  method span_is 247:5 (s: u32, l: u32, kw: str<64>) -> bool
  method span_is_ci 267:5 (s: u32, l: u32, kw: str<64>) -> bool
  method method_is 286:5 (m: str<64>) -> bool
  method path_is 293:5 (p: str<64>) -> bool
  method version_is 300:5 (v: str<64>) -> bool
  method find_header 308:5 (name: str<64>) -> u32
  method header_val_is 326:5 (i: u32, v: str<64>) -> bool
  method path_starts 334:5 (pre: str<64>) -> bool
  method path_param 346:5 (skip: u32) -> Option<str<64>>
  method wants_close 366:5 () -> bool
  method span_u32 385:5 (s: u32, l: u32) -> Option<u32>
  method content_length 414:5 () -> Option<u32>
  method is_chunked 427:5 () -> bool
  method reset 444:5 () var_self
  method span_copy 466:5 (s: str<256>, ln: u32) var_self -> bool
  method feed_line 490:5 (s: str<256>) var_self -> u32
  method feed_str 535:5 (s: str<256>) var_self -> u32
func req_new 565:1 () -> Req
struct Body 583:1
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
  method begin_cl 597:5 (n: u32) var_self
  method begin_chunked 612:5 () var_self
  method store 621:5 (b: u8) var_self -> bool
  method hexv 634:5 (b: u8) -> u32
  method size_end 652:5 () var_self -> u32
  method chunk_size 672:5 (b: u8) var_self -> u32
  method chunk_delim 708:5 (b: u8) var_self -> u32
  method chunk 745:5 (b: u8) var_self -> u32
  method push 769:5 (b: u8) var_self -> u32
  method is_done 796:5 () -> bool
  method at 804:5 (i: u32) -> u8
  method buf_is 812:5 (s: str<64>) -> bool
func body_new 832:1 () -> Body
struct Resp 845:1
  field buf :: [u8; 16384]
  field n :: u32
  field of :: bool
  method put_byte 850:5 (b: u8) var_self
  method put_str 862:5 (s: str<256>) var_self
  method put_dec 874:5 (v: u32) var_self
  method crlf 888:5 () var_self
  method status_line 897:5 (code: u32, text: str<64>) var_self
  method header_line 914:5 (name: str<64>, val: str<128>) var_self
  method body 936:5 (s: str<256>) var_self
  method content_length 949:5 (n: u32) var_self
  method end_headers 959:5 () var_self
func resp_new 967:1 () -> Resp
test http_reqline_ok 974:1
test http_header_ows_ci 991:1
test http_feed_str_batch 1007:1
test http_bad_reqline_400 1018:1
test http_bad_header_400 1028:1
test http_too_many_headers_431 1037:1
test http_path_param 1047:1
test http_wants_close 1073:1
test http_reset_reuse 1094:1
test http_resp_build 1118:1
test http_content_length 1131:1
test http_body_cl 1160:1
test http_body_cl_413 1184:1
test http_body_chunked 1193:1
test http_body_chunked_400 1233:1
module lib/Io.eat 1240:1
export read_line 8:5 :: read_line
func read_line 11:1 () -> Result<str<256>, IoError>
module lib/Json.eat 29:1
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
import hex_val 36:5 :: lib/Hex.eat hex_val
const JSENT 41:1 :: u32 = 4294967295
const J_NULL 44:1 :: u32 = 0
const J_BOOL 45:1 :: u32 = 1
const J_NUM 46:1 :: u32 = 2
const J_STR 47:1 :: u32 = 3
const J_ARR 48:1 :: u32 = 4
const J_OBJ 49:1 :: u32 = 5
enum JErr 52:1
  variant Capacity
  variant Depth
  variant Input
  variant Syntax
  variant Num
  variant Str
struct JNode 63:1
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
struct JDoc 77:1
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
  method put 115:5 (b: u8) var_self
  method load 127:5 (s: str<256>) var_self
  method clear 139:5 () var_self
  method cb 150:5 () -> u8
  method skip_ws 160:5 () var_self
  method next 175:5 () var_self -> u32
  method lex_str 222:5 () var_self -> u32
  method esc 257:5 () var_self
  method esc_u 286:5 () var_self
  method lex_word 326:5 () var_self -> u32
  method word_is 346:5 (w: str<8>) -> bool
  method lex_num 369:5 () var_self -> u32
  method aput 448:5 (b: u8) var_self
  method alloc 464:5 (k: u32) var_self -> u32
  method value 490:5 (k: u32) var_self -> u32
  method attach 532:5 (id: u32) var_self
  method push 561:5 (id: u32, obj: bool) var_self
  method on_value 581:5 (k: u32) var_self
  method step 600:5 (k: u32) var_self
  method rewind 660:5 () var_self
  method run 676:5 () var_self
  method jerr 707:5 () -> JErr
  method validate 734:5 () var_self -> Result<u32, JErr>
  method parse 750:5 () var_self -> Result<u32, JErr>
  method kind_of 764:5 (id: u32) -> u32
  method is_null 771:5 (id: u32) -> bool
  method as_int 780:5 (id: u32) -> Option<i32>
  method as_i64 797:5 (id: u32) -> Option<i64>
  method num_mant 808:5 (id: u32) -> Option<i64>
  method num_exp 819:5 (id: u32) -> Option<i32>
  method as_bool 829:5 (id: u32) -> Option<bool>
  method count 840:5 (id: u32) -> u32
  method at 857:5 (id: u32, i: u32) -> Option<u32>
  method get 881:5 (id: u32, key: str<256>) -> Option<u32>
  method span_is 907:5 (off: u32, ln: u32, s: str<256>) -> bool
  method key_is 928:5 (id: u32, key: str<256>) -> bool
  method str_is 935:5 (id: u32, s: str<256>) -> bool
  method str_len 945:5 (id: u32) -> u32
  method as_str 955:5 (id: u32) -> Option<str<256>>
struct JOut 985:1
  field n :: u32
  field over :: bool
  field deep :: bool
  field sc :: [u32; 64]
  field scur :: [u32; 64]
  field sd :: u32
  field buf :: [u8; 65536]
  method byte 994:5 (b: u8) var_self
  method word 1005:5 (w: str<8>) var_self
  method num 1019:5 (mant: i64, exp: i32) var_self
  method uesc 1066:5 (b: u8) var_self
  method eb 1088:5 (b: u8) var_self
  method qstr 1129:5 (d: JDoc, off: u32, ln: u32) var_self
  method open 1145:5 (id: u32, kid: u32) var_self
  method val 1158:5 (d: JDoc, id: u32) var_self
  method walk 1191:5 (d: JDoc) var_self
  method ser 1223:5 (d: JDoc, root: u32) var_self -> Result<u32, JErr>
  method out_is 1248:5 (s: str<256>) -> bool
func json_doc 1269:1 () -> JDoc
func json_out 1286:1 () -> JOut
test json_scalars 1296:1
test json_object 1345:1
test json_escapes 1390:1
test json_errors 1414:1
test json_depth 1489:1
test json_capacity 1514:1
test json_input_overflow 1536:1
test json_validate 1556:1
test json_ser 1575:1
test json_frac_parse 1603:1
test json_frac_roundtrip 1662:1
module lib/Num.eat 1691:1
export min 7:5 :: min
export max 8:5 :: max
export clamp 9:5 :: clamp
func min 12:1 (a: u32, b: u32) -> u32
func max 22:1 (a: u32, b: u32) -> u32
func clamp 32:1 (x: u32, lo: u32, hi: u32) -> u32
test num_min_max 45:1
test num_clamp 56:1
module lib/Parse.eat 62:1
export parse_i32 8:5 :: parse_i32
func parse_i32 11:1 (s: str<256>) -> Result<i32, ParseError>
test parse_i32_ok 86:1
test parse_i32_err 105:1
module lib/Server.eat 137:1
export Server 23:5 :: Server
export server_listen 24:5 :: server_listen
export Bytes 25:5 :: Bytes
export bytes_new 26:5 :: bytes_new
export port_arg 27:5 :: port_arg
export not_found 28:5 :: not_found
export bad_request 29:5 :: bad_request
export too_large 30:5 :: too_large
export too_many_headers 31:5 :: too_many_headers
export method_not_allowed 32:5 :: method_not_allowed
export err_resp 33:5 :: err_resp
export PORT_DEFAULT 34:5 :: PORT_DEFAULT
import Req 38:5 :: lib/Http.eat Req
import req_new 39:5 :: lib/Http.eat req_new
import Resp 40:5 :: lib/Http.eat Resp
import resp_new 41:5 :: lib/Http.eat resp_new
import PARSE_MORE 42:5 :: lib/Http.eat PARSE_MORE
import get 46:5 :: lib/Args.eat get
import parse_i32 50:5 :: lib/Parse.eat parse_i32
const PORT_DEFAULT 54:1 :: u32 = 8080
const SRV_NO_CONN 56:1 :: u32 = 4294967295
const SRV_SENT 58:1 :: u32 = 4294967295
const DRAIN_BUDGET 60:1 :: u32 = 8900
const HEAD_BUDGET 63:1 :: u32 = 64
const BODY_BUDGET 64:1 :: u32 = 70000
struct Bytes 69:1
  field buf :: [u8; 65536]
  field n :: u32
  field over :: bool
  method put_byte 76:5 (b: u8) var_self
  method put_str 88:5 (s: str<256>) var_self
  method clear 102:5 () var_self
  method at 111:5 (i: u32) -> u8
func bytes_new 119:1 () -> Bytes
struct Server 130:1
  field lst :: u32
  field live :: bool
  field conn :: u32
  field served :: u32
  field req :: Req
  field st :: u32
  field eof :: bool
  field wc :: u32
  method tick 146:5 () var_self -> u32
  method reply 187:5 (w: Resp) var_self
  method reply_bytes 206:5 (head: Resp, b: Bytes) var_self
  method drop_conn 232:5 () var_self
  method stop 243:5 () var_self
func server_listen 254:1 (port: u16) -> Result<Server, IoError>
func port_arg 273:1 () -> u32
func simple 295:1 (code: u32, text: str<64>, msg: str<256>) -> Resp
func not_found 307:1 () -> Resp
func bad_request 314:1 () -> Resp
func too_large 321:1 () -> Resp
func too_many_headers 328:1 () -> Resp
func method_not_allowed 335:1 () -> Resp
func err_resp 343:1 (st: u32) -> Resp
test server_port_default 356:1
test server_bytes_carrier 363:1
test server_err_resp_codes 376:1
module lib/U128.eat 390:1
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
  method mul 431:5 (o: U128) -> U128
  method mul_wrap 476:5 (o: U128) -> U128
  method divrem 517:5 (o: U128) -> U128DivRem
  method divrem_64 540:5 (d: u64) -> U128DivRem
  method divrem_wide 562:5 (o: U128) -> U128DivRem
  method divrem_32 605:5 (d: u64) -> U128DivRem
  method div 631:5 (o: U128) -> U128
  method rem 643:5 (o: U128) -> U128
  method repr_hex 658:5 () -> str<32>
  method repr_dec 687:5 () -> str<40>
func u128 275:1 (lo: u64) -> U128
func u128_hi_lo 284:1 (hi: u64, lo: u64) -> U128
func mul_64 296:1 (a: u64, b: u64) -> U128
struct U128DivRem 319:1
  field q :: U128
  field r :: U128
struct Qr64 325:1
  field q :: u64
  field r :: u64
func clz64 332:1 (x: u64) -> u64
func div_step 371:1 (pre: u64, nxt: u64, dn: u64) -> Qr64
func divlu 406:1 (u1: u64, u0: u64, d: u64) -> Qr64
struct I128 718:1
  field sgn :: bool
  field mag :: U128
  method is_zero 751:5 () -> bool
  method eq 758:5 (o: I128) -> bool
  method lt 765:5 (o: I128) -> bool
  method le 781:5 (o: I128) -> bool
  method neg 788:5 () -> I128
  method abs 797:5 () -> I128
  method add 807:5 (o: I128) -> I128
  method sub 824:5 (o: I128) -> I128
  method mul 836:5 (o: I128) -> I128
  method to_i64 848:5 () -> i64
  method repr_dec 861:5 () -> str<40>
  method divrem 883:5 (o: I128) -> I128DivRem
  method div 900:5 (o: I128) -> I128
  method rem 912:5 (o: I128) -> I128
func i128_make 724:1 (sgn: bool, mag: U128) -> I128
func i128 738:1 (v: i64) -> I128
struct I128DivRem 874:1
  field q :: I128
  field r :: I128
test u128_ctor_edges 925:1
test u128_add_sub_edges 940:1
test u128_cmp 955:1
test u128_mul64_edges 970:1
test u128_mul_edges 980:1
test u128_shifts 995:1
test u128_divrem 1011:1
test u128_divrem_64 1033:1
test u128_div_paths 1059:1
test u128_repr 1081:1
test i128_basics 1095:1
test i128_arith 1112:1
test i128_cmp 1127:1
test i128_divrem 1139:1
test i128_repr 1151:1
module lib/Fixed.eat 1158:1
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
import Req 45:5 :: lib/Http.eat Req
import req_new 46:5 :: lib/Http.eat req_new
import read_line 50:5 :: lib/Io.eat read_line
import JDoc 54:5 :: lib/Json.eat JDoc
import json_doc 55:5 :: lib/Json.eat json_doc
import min 59:5 :: lib/Num.eat min
import parse_i32 63:5 :: lib/Parse.eat parse_i32
import server_listen 67:5 :: lib/Server.eat server_listen
import mul_64 71:5 :: lib/U128.eat mul_64
func main 74:1 ()
stats funcs=243 structs=20 stmts=1915
