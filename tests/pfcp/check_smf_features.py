#!/usr/bin/env python3
"""Compile exact original/patched decoder methods; replay IE43 from a PCAP.
Method-level harness, not a complete SMF binary/integration test.
Usage: python3 tests/pfcp/check_smf_features.py BASELINE_HEADER PCAP
"""
import pathlib, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[2]
header, pcap = map(pathlib.Path, sys.argv[1:])
def method(s):
    start=s.index('  void load_from(std::istream& is) {',s.index('class pfcp_up_function_features_ie'))
    return s[start:s.index('\n  //--------',start)]
raw=subprocess.check_output(['tshark','-r',str(pcap),'-Y','pfcp.msg_type == 6','-T','fields','-e','udp.payload'],text=True)
payloads=[]
for line in raw.splitlines():
    packet=bytes.fromhex(line.replace(':','')); pos=8
    while pos < len(packet):
        typ=int.from_bytes(packet[pos:pos+2],'big'); n=int.from_bytes(packet[pos+2:pos+4],'big')
        value=packet[pos+4:pos+4+n]; assert len(value)==n
        if typ==43: payloads.append(value)
        pos+=4+n
assert payloads and all(x==bytes.fromhex('1000000000000000') for x in payloads)
with tempfile.TemporaryDirectory() as td:
    d=pathlib.Path(td); (d/'pfcp').mkdir();(d/'pfcp/3gpp_29.244.hpp').write_bytes(header.read_bytes())
    subprocess.run(['patch','-p1','-i',str(ROOT/'patches/oai-smf-v2.2.0-pfcp-up-features-extension.patch')],cwd=d,check=True)
    original=method(header.read_text()); patched=method((d/'pfcp/3gpp_29.244.hpp').read_text())
    stub='''#include <sstream>
#include <stdexcept>
#include <cassert>
#include <cstdint>
struct pfcp_tlv_bad_length_exception : std::runtime_error {
 pfcp_tlv_bad_length_exception(int,int,const char*,int):runtime_error("length"){} };
struct Base { struct TLV { unsigned n; int type=43; unsigned get_length(){return n;} } tlv;
 struct Octet { uint8_t b=255; } u1,u2,u3,u4,u5,u6;
};
'''
    code=stub+'struct Original: Base {\n'+original+'\n};\nstruct Patched: Base {\n'+patched+'\n};\n'
    data=''.join('\\x%02x'%x for x in payloads[0])
    code+='''int main(){
 Original old; old.tlv.n=8; std::istringstream a(std::string("'''+data+'''",8));
 bool rejected=false; try { old.load_from(a); } catch(const pfcp_tlv_bad_length_exception&) {rejected=true;} assert(rejected);
 for(unsigned n: {2,3,4,5,6,7,8,9,255}) {
  Patched p; p.tlv.n=n; std::string body(n,'\\0'); body[0]=0x10;
  if(n>6) body[6]=char(0xff);
  std::istringstream in(body+"NEXT"); p.load_from(in);
  assert(p.u1.b==0x10 && p.u2.b==0 && p.u6.b==0);
  std::string next(4,'\\0'); in.read(&next[0],4); assert(next=="NEXT");
 }
 for(unsigned n: {0,1,2,6,8,9}) {
  Patched p; p.tlv.n=n; std::istringstream in(std::string(n?n-1:0,'\\0'));
  bool failed=false; try {p.load_from(in);} catch(const pfcp_tlv_bad_length_exception&){failed=true;} assert(failed);
 }
}
'''
    (d/'test.cpp').write_text(code)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra',str(d/'test.cpp'),'-o',str(d/'test')],check=True)
    subprocess.run([str(d/'test')],check=True)
print(f'PASS: {len(payloads)} captured IE43 payloads identical; original rejects length=8; patched decoder preserves FTUP, consumes extensions, preserves next IE, rejects short/truncated payloads. Runtime SMF NOT TESTED.')
