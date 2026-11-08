"""Independent replay of a fixed packet-loss counterexample.
Uses a separate wrapper, ELF and hardcoded wire stream; no producer oracle enters C.
CPU emulation only. Instruction counts are not hardware timing.
"""
import sys,json,hashlib,subprocess,struct,os
from pathlib import Path
D=Path(__file__).resolve().parent
ROOT=D.parent
# Dependencies are installed in the selected Python environment.
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS
from unicorn.arm_const import UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_R0,UC_ARM_REG_PC
from elftools.elf.elffile import ELFFile
GCC=Path(os.environ['ARM_GCC'])
V=Path(os.environ['CCSDS124_SOURCE'])
WIRES=[bytes.fromhex('81bd9800000000000000000000000000'),bytes.fromhex('ebf0b0'),bytes.fromhex('83')]
VALID_BITS=[126,20,8]
ORIGINALS=[bytes(13),bytes([1])+bytes(12),bytes([1])+bytes(12)]
class DUT:
    def __init__(self,path):
        self.u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
        self.u.mem_map(0x10000,0x100000)
        with path.open('rb') as f:
            e=ELFFile(f)
            for s in e.iter_segments():
                if s['p_type']=='PT_LOAD' and s['p_filesz']:
                    self.u.mem_write(s['p_vaddr'],s.data())
            self.names={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    def call(self,n):
        self.u.reg_write(UC_ARM_REG_SP,0x10e000)
        self.u.reg_write(UC_ARM_REG_LR,0x10f001)
        self.u.emu_start(self.names[n]|1,0x10f000,count=2000000)
        if self.u.reg_read(UC_ARM_REG_PC)!=0x10f000:raise RuntimeError('function did not return')
        r=self.u.reg_read(UC_ARM_REG_R0)
        return r if r<2**31 else r-2**32
    def receive(self,b,bits=None):
        self.u.mem_write(self.names['input_bytes'],b)
        self.u.mem_write(self.names['input_bits'],struct.pack('<I',len(b)*8 if bits is None else bits))
        rc=self.call('receive')
        return {'rc':rc,'output':bytes(self.u.mem_read(self.names['output_bytes'],13)).hex(),'flags':list(self.u.mem_read(self.names['observed_flags'],4))}
def replay(path,lose,exact_bits=False):
    d=DUT(path); assert d.call('initialize')==0
    trace=[]
    for i,b in enumerate(WIRES):
        if lose and i==1:
            assert d.call('erase_one')==0; trace.append({'index':i,'erased':True});continue
        x=d.receive(b,VALID_BITS[i] if exact_bits else None); x['index']=i
        x['expected']=ORIGINALS[i].hex();x['matches']=x['output']==x['expected'];trace.append(x)
    return trace
def main():
    results={'scope':'compiled Cortex-M4 C executed in Unicorn CPU emulation; no physical peripherals/timing/flight claim','wire_hex':[w.hex() for w in WIRES],'vendor_hashes':{},'cases':[]}
    for p in [V/'include'/'ccsds124.h',V/'src'/'decompress.c',V/'src'/'bitvector.c']:
        results['vendor_hashes'][str(p.relative_to(V))]=hashlib.sha256(p.read_bytes()).hexdigest()
    for opt in ['-O0','-O2']:
        for maximum in [104,2048]:
            elf=D/(opt[1:]+'_'+str(maximum)+'.elf')
            cmd=[str(GCC),'-mcpu=cortex-m4','-mthumb',opt,'-ffreestanding','-fno-builtin','-nostdlib','-DCCSDS124_MAX_PACKET_LENGTH='+str(maximum),'-I'+str(V/'include'),str(D/'independent_wrapper.c'),str(V/'src'/'bitvector.c'),str(V/'src'/'decompress.c'),'-T',str(D/'link.ld'),'-lgcc','-o',str(elf)]
            p=subprocess.run(cmd,capture_output=True,text=True); assert p.returncode==0,p.stderr
            for exact in [False,True]:
                full=replay(elf,False,exact); lost=replay(elf,True,exact)
                assert all(x['matches'] and x['rc']==0 for x in full),'no-loss control failed'
                assert lost[-1]['rc']==0 and not lost[-1]['matches'],'counterexample did not reproduce'
                results['cases'].append({'optimization':opt,'maximum_packet_bits':maximum,'exact_valid_bits':exact,'command':cmd,'elf_sha256':hashlib.sha256(elf.read_bytes()).hexdigest(),'no_loss':full,'one_known_erasure':lost})
    (D/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps({'independent_builds':4,'reception_configurations':len(results['cases']),'no_loss_controls_passed':True,'false_accuracy_guarantee_reproduced':True,'lost_packet_notify_called':True},indent=2))
if __name__=='__main__':main()

