#!/usr/bin/env python3

# tinyssb/repository.py  -- disk storage for logs and blobs (sidechains)
# 2022-04-06 <christian.tschudin@unibas.ch>

'''
directory structure of a repository:

  path_to_repo_data/
      +--> config.json
      +--> _logs
      |       +--> FID1_IN_HEX.log
      |       `--> FID2_IN_HEX.log
      `--> _blob
              +--> 05/REST_OF_HASHPTR1_IN_HEX
              +--> 05/REST_OF_HASHPTR2_IN_HEX
              `--> AA/REST_OF_HASHPTR3_IN_HEX

blobs: stored as files of length 120
logs: see end of this file for a description of the log file format,
      it's a multiple of 120B
'''

import hashlib
import os

from . import packet, util
from .dbg import *

if sys.implementation.name == 'micropython':
    def isfile(fn):
        try:    return os.stat(fn)[0] & 0x8000 != 0
        except: return False

    def isdir(dn):
        try:    return os.stat(dn)[0] & 0x4000 != 0  # FIXME dn instead of fn?
        except: return False
else:
    isfile = os.path.isfile
    isdir  = os.path.isdir


class REPO:

    def __init__(self, path, verify_signature_fct):
        self.path = path
        self.vfct = verify_signature_fct  # bool, signature verification successful
        try: os.mkdir(self.path + '/_logs')
        except: pass
        try: os.mkdir(self.path + '/_blob')
        except: pass
        self.open_logs = {}

    def _feed_index(self, fid: bytearray) -> int:
        for i, f in enumerate(self.listlog()):
            if f == fid:
                return i
        
        return -1

    def _log_fn(self, fid):
        """
        Path to the file for a log entry.
        :param fid: SSB identity
        :return: path to the (local) log for the corresponding fid
        """
        return self.path + '/_logs/' + util.hex(fid) + '.log'

    def _blob_fn(self, hashval):
        """Path to the file for a blob"""
        h = util.hex(hashval)
        return self.path + '/_blob/' + h[:2] + '/' + h[2:]

    def listlog(self):
        lst = []
        for fn in os.listdir(self.path + '/_logs/'):
            lst.append(util.fromhex(fn.split('.')[0]))
        return lst

    def allocate_log(self, fid, trusted_seq, trusted_msgID,
                     buf120=None, parent_fid=bytes(32), parent_seq=0):
        """
        Allocate space for a remote log to be synced
        """
        # use this to create a file where entries can start at any index
        fn = self._log_fn(fid)  # file_name
        if isfile(fn):
            return None
        hdr = bytes(4)  # should have version and other magic bytes
        hdr += fid
        hdr += parent_fid + parent_seq.to_bytes(4, 'big')
        buf = trusted_seq.to_bytes(4, 'big') + trusted_msgID
        hdr += buf
        if buf120 == None:
            hdr += buf  # copy trusted seq number as front information
            pass
        else:
            pkt = packet.from_bytes(buf120, fid, trusted_seq + 1, trusted_msgID,
                                    self.vfct)
            if pkt == None: return None
            hdr += pkt.seq.to_bytes(4, 'big') + pkt.mid  # as front
        assert len(hdr) == 120, "log file header must be 120B"
        # dbg(BLU, f"WRITE:\nhdr: {util.hex(hdr)};\nbuf: {util.hex(buf120)}")
        with open(fn, 'wb') as f:
            f.write(hdr)
            if buf120 != None: f.write(buf120)
        return self.get_log(fid)

    def mk_generic_log(self, fid, typ, buf48, signFct,
                       parent_fid=bytes(32), parent_seq=0):
        """Create a log file where entries start at seq=fid[:20]"""
        prev = fid[:20]  # this is a convention, like a self-signed cert
        genesis_block = packet.PACKET(fid, 1, prev)
        genesis_block.mk_typed_entry(typ, buf48, signFct)
        return self.allocate_log(fid, 0, prev, genesis_block.wire,
                                 parent_fid, parent_seq)

    def mk_child_log(self, parentFID, parentSign, childFID, childSign,
                     usage=bytes(16)):
        payload = childFID + usage
        assert len(payload) == 48
        p = self.get_log(parentFID)
        pkt = p.write_typed_48B(payload, packet.PKTTYPE_mkchild, parentSign)
        # FIXME specification says that last 12 bytes of 'PKTTYPE_ischild'
        #  (and of 'PKTTYPE_iscontn') = hash(fid[seq]) (fid and seq from
        #  referenced packet from other feed), but here we use the last
        #  12B of the (64B) signature. switching "pkt.wire" by "pkt.payload"
        #  is not safe though, as last 16B are (currently) zeros
        buf48 = pkt.fid + pkt.seq.to_bytes(4, 'big') + pkt.wire[-12:]
        newFeed = self.mk_generic_log(childFID, packet.PKTTYPE_ischild,
                                      buf48, childSign, pkt.fid, pkt.seq)
        return [pkt, newFeed[1]]

    def mk_continuation_log(self, prevFID, prevSign, contFID, contSign):
        # return both packets that were gerenated and appended
        p = self.get_log(prevFID)
        pkt = p.write_typed_48B(contFID + bytes(16),
                                packet.PKTTYPE_contdas, prevSign)
        buf48 = pkt.fid + pkt.seq.to_bytes(4, 'big') + pkt.wire[-12:]
        newFeed = self.mk_generic_log(contFID, packet.PKTTYPE_iscontn,
                                      buf48, contSign)
        return [pkt, newFeed[1]]

    def get_log(self, fid):
        """
        Obtain an instance of LOG
        :param fid: bin encoded feed id
        :return: a LOG, or None
        """
        if not fid in self.open_logs:
            fn = self._log_fn(fid)  # file name
            if not isfile(fn):
                return None
            l = LOG(fn, self.vfct, self)
            if l == None:
                return None
            self.open_logs[fid] = l
        return self.open_logs[fid]

    def del_log(self, fid):
        if fid in self.open_logs:
            feed = self.open_logs[fid]
            feed.file.close()
            del self.open_logs[fid]
        fn = self._log_fn(fid)
        os.unlink(fn)

    def add_blob(self, buf120):
        hptr = hashlib.sha256(buf120).digest()[:20]
        fn = self._blob_fn(hptr)
        dn = fn[:-39]
        if not isdir(dn):   os.mkdir(dn)
        if isfile(fn):      return
        with open(fn, "wb+") as f:
            f.write(buf120)
        return hptr

    def fetch_blob(self, hashptr):
        try:
            with open(self._blob_fn(hashptr), "rb") as f:
                return f.read(120)
        except Exception as e:
            # print("get_blob", e)
            pass
        return None
    
    def get_blob(self, fid: bytearray, seq: int, bnr: int) -> bytearray | None:
        log = self.get_log(fid)
        if not log:
            return None
        e = log[seq]
        if not e:
            return None

        e.undo_chain(lambda h: self.fetch_blob(h))
        print("first blob:", e.chain_firstptr)
        
        next = e.chain_firstptr
        i = 0
        while next is not None and next != bytes(20):
            content = self.fetch_blob(next)
            if not content:
                print("Content null")
                return
            if (i == bnr):
                return content
            i += 1
            next = content[-20:]
        
        return None
    

    def persist_chain(self, pkt, blobs):
        # first persist the blobs as otherwise we could have stored the
        # log entry but not all blobs, in case of a node crash
        for b in blobs:
            self.add_blob(b)
        feed = self.get_log(pkt.fid)
        # should we check our own signature here, use feed.append(pkt.wire)?
        feed._append(pkt)
        return [pkt.wire] + blobs

    '''
    def get_peer(fid): # -> PEER
        pass

    def get_user(fid): # -> USER
        pass

    def __del__(self):
       delete all log objects in self.open_logs
    '''

# ----------------------------------------------------------------------

class LOG:

    def __init__(self, fileName, verify_signature_fct, repo):
        # self.fn = fn
        self.verify_fct = verify_signature_fct
        self.file = open(fileName, 'rb+')
        # dbg(BLU, f"READ:\n{util.hex(self.file.read())}")
        # for i in range(4):
        #     dbg(BLU, f"\n{i}: {util.hex(self.file.read(120))}")
        self.repo = repo
        self.file.seek(0)
        hdr = self.file.read(120)
        hdr = hdr[4:]  # first 4B unused
        self.fid = hdr[:32]
        self.parfid = hdr[32:64]
        self.parseq = int.from_bytes(hdr[64:68], 'big')
        self.anchrS = int.from_bytes(hdr[68:72], 'big')  # trusted seqNr
        self.anchrM = hdr[72:92]                         # trusted msgID
        self.frontS = int.from_bytes(hdr[92:96], 'big')  # seqNr of last rec
        self.frontM = hdr[96:116]                        # msgID of last rec
        self.file.seek(0, 2)
        assert self.file.tell() == 120 + 120 * (self.frontS - self.anchrS), \
            f"log file length mismatch: {self.file.tell()} != {120 + 120 * (self.frontS - self.anchrS)}"
        self.acb = None  # append callback
        self.subscription = 0

    def __getitem__(self, seq):
        if seq > self.frontS:
            raise IndexError
        if seq < 0:
            seq = self.frontS + seq + 1
            if seq < 0:
                raise IndexError
        pos = 120 * (seq - self.anchrS)
        try:
            self.file.seek(pos)
        except ValueError:
            dbg(RED, f"Seeking of a closed file: {self.file.name}")
            return None
        buf = self.file.read(120)
        if not buf or len(buf) == 0: return None
        mid = self.anchrM if seq == self.anchrS + 1 else bytes(20)
        return packet.from_bytes(buf, self.fid, seq, mid, None)

    def __len__(self):
        return self.frontS

    def __del__(self):
        try:
            self.file.close()
        except Exception as e:
            dbg(MAG, f"Exception e: {e} for __{self}__")

    def _append(self, pkt):
        assert pkt.seq == self.frontS + 1, "new log entry not in sequence"
        # append to file:
        self.file.seek(0, 2)
        self.file.write(pkt.wire)
        # update file header:
        self.frontS += 1
        self.frontM = pkt.mid
        self.file.seek(4 + 92)  # position of front fields
        self.file.write(self.frontS.to_bytes(4, 'big') + self.frontM)
        self.file.flush()
        # os.fsync(self.f.fileno())
        return pkt

    def append(self, buf120):
        pkt = packet.from_bytes(buf120, self.fid, self.frontS + 1, self.frontM,
                                self.verify_fct)
        if pkt == None: return None
        self._append(pkt)
        if int.from_bytes(pkt.typ) == packet.PKTTYPE_chain20:
            pkt.undo_chain(lambda h: self.repo.fetch_blob(h))
        if pkt.content_is_complete():
            if self.acb != None:
                self.acb(pkt)
        return pkt

    def write_plain_48B(self, buf48, signfct):
        return self.write_typed_48B(buf48, packet.PKTTYPE_plain48, signfct)

    def write_typed_48B(self, buf48, typ, signfct):
        """
        Create a packet and compute signature.
        :param typ: 1 byte type
        :param buf48: payload (will be padded)
        :param signfct: signature fct
        :return: updated self
        """
        # FIXME assert that feed wasn't terminated by eof
        assert len(buf48) == 48
        e = packet.PACKET(self.fid, self.frontS + 1, self.frontM)
        e.mk_typed_entry(typ, buf48, signfct)
        return self.append(e.wire)

    def write_eof(self, signfct):
        # FIXME delete: bypasses lock and do not push. Use node.write_typed_48B instead
        return self.write_typed_48B(bytes(48), packet.PKTTYPE_contdas, signfct)

    def prepare_chain(self, buf, signfct):  # returns list of packets, or None
        e = packet.PACKET(self.fid, self.frontS + 1, self.frontM)
        blobs = e.mk_chain(buf, signfct)
        return e, blobs

    def getfront(self):
        return (self.frontS, self.frontM)

    def set_append_cb(self, fct=None):
        self.acb = fct

# ----------------------------------------------------------------------

'''
A) Internal structure of an append-only log file:

  How 'anchor' and 'front' metadata relate to an append-only log:

                  v-- first log entry in file (seq=N)
   -  -  -  -  +-----------+-----------+-----------+-----------+
   log         |R+D+T+P+SIG|R+D+T+P+SIG|R+D+T+P+SIG|R+D+T+P+SIG| --> future
   -  -  -  -  +-----------+-----------+-----------+-----------+
          ^                   last log entry in file --^   ^
          |                                                |
          | anchorSEQ (N-1)                       frontSEQ |
          | anchorMID                             frontMID |


  The log file is a sequence of 120 byte blocks, the first is a header block

    120B header block
    120B log entry N
    120B log entry N+1
         ..


  The header block persists critical metadata for the log:
  - reserved   ( 4B)
  - feed ID    (32B, ed25519 public key)
  - parent ID  (32B, if this log is a subfeed)
  - parent SEQ ( 4B, seqNr where the parent feed declared this subfeed)
  - anchor SEQ ( 4B, seqNr, assumed to be trusted, can be >0 for truncated feed
  - anchor MID (20B, msgID, assumed to be trusted, of above anchorSEQ entry
  - front SEQ  ( 4B, seq number of last record in the file)
  - front MID  (20B, msgID of last record in the file)

 
  Log entries, following the header block, occupy also 120 bytes:
  - packet     (120B, DMX+T+PAYLOAD+SIGNATURE)
  Once a log entry is in the file, it is declared trusted
  (because we verify each packet before appending it)


B) Blobs:

  - any         (120B)
  - stored in a separate directory


C) Sidenote, unrelated to this repository code:

   One can use a log entry with a sidechain to tunnel packets of
   other feeds i.e., wrapping a feed inside another feed, or to
   tunnel a mix (of log entries from several feeds) inside a single feed.

   Given a (inner) packet X of length 120B (data), create two (outer) packets:

   i) log entry   D+T+P+SIG, where T is chain20
                                   P is 28B (data from X) + 20B (hptr)

   ii) blob       100B (data from X) + 20B (null-ptr)


'''

# eof
