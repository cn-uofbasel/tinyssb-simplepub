#

# tinyssb/node.py   -- node (peering and replication) behavior
# 2022-04-09 <christian.tschudin@unibas.ch>


import base64
import hashlib
import _thread
import json
import os

from . import io, packet, util, repository
from .dbg import *
from .exception import TinyException
import bipf

LOGTYPE_private = 0x00  # private fid (not to be shared)
LOGTYPE_public  = 0x01  # public fid to synchronise with peers
LOGTYPE_remote  = 0x02  # public fid from a remote peer

NOVELTY_LEN = 33
FID_LEN = 32
novelty_credit = 1
DMX_PFX = "tinyssb-v0".encode('utf-8')
DMX_LEN = 7
TINYSSB_PKT_LEN = 120
HASH_LEN = 20

class Novelty:
    type = 'n'
    key = bytearray(FID_LEN)
    wire = bytearray(0)


class NODE:  # a node in the tinySSB forwarding fabric

    def __init__(self, faces, keystore, repo, me, callback=None):
        from . import goset
        self.faces = faces
        self.ks = keystore
        self.repo  = repo
        self.dmxt  = {}    # DMX  ~ dmx_tuple  DMX filter bank
        self.blbt  = {}    # hptr ~ blob_obj  blob filter bank
        self.logs = { util.hex(me): LOGTYPE_private }
        self.timers = []
        self.comm = {}
        #
        self.me = me
        self.pending_chains = {}
        self.next_timeout = [0]
        self.ndlock = _thread.allocate_lock()
        self.want_dmx = None
        self.chnk_dmx = None
        self.goset = goset.GOset(self)
        self.log_offs = 0
        self.callback= callback

    def activate_log(self, fid, log_type):
        """
        Keeps track of all the active private, public and remote feeds
        """
        hex_fid = util.hex(fid)
        if log_type not in [LOGTYPE_private, LOGTYPE_public, LOGTYPE_remote]:
            raise TinyException(f"'{log_type}' is not a log type")
        self.ndlock.acquire()
        self.logs[hex_fid] = log_type
        self.ndlock.release()
        if log_type == LOGTYPE_remote:
            # If it doesn't exist, allocate space for the remote log
            log = self.repo.get_log(fid)
            
            if log is not None:
                log.set_append_cb(self.callback)
                # self.request_latest(log, "Add new log")
                pass
            else:
                log = self.repo.allocate_log(fid, 0, fid[:20])
                log.set_append_cb(self.callback)

    def deactivate_log(self, fid):
        hex_fid = util.hex(fid)
        try:
            self.ndlock.acquire()
            self.logs.pop(hex_fid)
            del self.repo.open_logs[fid]
            self.ndlock.release()
        except KeyError:
            self.ndlock.release()
            # dbg(YEL, f"Deactivate log: there is no log with id = {hex_fid}")

    def start(self):
        self.faces[0].on_rx = self.on_rx
        # self.ioloop = io.IOLOOP(self.faces, self.on_rx)
        # dbg(TERM_NORM, '  starting thread with IO loop')

        print(self.me.hex())

        if not self.repo.listlog():
            self.repo.allocate_log(self.me, 0, self.me[:20])

        for log in self.repo.listlog():
            self.activate_log(log, LOGTYPE_remote)
            self.goset._include_key(log)
        
        self.goset.adjust_state()

        self.arm_dmx(self.goset.goset_dmx,  lambda buf, n: self.goset.rx(buf, n))

        _, name = self.ks.kv[self.me]
        path = util.DATA_FOLDER + name + '/_backed/pending_chains.json'
        if os.path.exists(path):
            with open(path) as f:
                j = json.load(f)
                for c in j:
                    val = j[c]  # [base64(fid), seq, blbt_ndx]
                    hptr = util.fromhex(c)
                    fid = util.fromhex(val[0])
                    seq = int(val[1])
                    blbt_ndx = int(val[2])
                    self.pending_chains[hptr] = (fid, seq, blbt_ndx)
                    self.arm_blob(hptr, lambda buf: self.incoming_chainedblob(buf,fid,seq,blbt_ndx + 1))
            print("loaded pending:", self.pending_chains)

        # _thread.start_new_thread(self.ioloop.run, tuple())
        # dbg(TERM_NORM, "  starting thread with arq loop")
        _thread.start_new_thread(self.goset.loop, tuple())
        _thread.start_new_thread(self.arq_loop, tuple())
       

    def arm_dmx(self, dmx, fct=None, comment=None):
        """
        Add or delete a dmx entry.

        Call with a lambda function to prepare for the next message
        for this feed, without function to delete the entry when the
        message has been received
        :param dmx: demultiplexing field, 7 bytes
        :param fct: function to call when the packet arrives
        :param comment: description comment
        :return: nothing
        """
        if fct == None:
            if dmx in self.dmxt: del self.dmxt[dmx]
            if dmx in self.comm: del self.comm[dmx]
        else:
            # print(f"+dmx {util.hex(dmx)} / {comment}")
            self.dmxt[dmx] = fct
            self.comm[dmx] = comment

    def arm_blob(self, hptr, fct=None):
        """
        See arm_dmx
        """
        if not fct:
            if hptr in self.blbt: del self.blbt[hptr]
        else:
            self.blbt[hptr] = fct

    def on_rx(self, buf, neigh):
        """
        Manages the reception from all interfaces
        :param buf: the message
        :param neigh: Interfaces available (added in IOLOOP.run)
        :return: nothing
        """
        # all tSSB packet reception logic goes here!
        # dbg(GRE, "<< buf", len(buf), util.hex(buf[:20]), "...")
        # if len(buf) == 120:
            # try: dbg(RED, "<< is", bipf.loads(buf[8:56]))#, "...", buf[:7] in self.dmxt)
            # except: pass
        
        

        dmx = buf[:7] # DMX_LEN = 7

        print("received " + dmx.hex())
        
        if dmx in self.dmxt:
            self.dmxt[dmx](buf, neigh)
        else:
            hptr = hashlib.sha256(buf).digest()[:20] # HASH_LEN = 20
            if hptr in self.blbt:
                self.blbt[hptr](buf)
            else:
                fid = bytes(buf[8:40])
                p = packet.from_bytes(buf, fid, 1, fid[:20],
                                      lambda f, mssg, sig: self.ks.verify(f, mssg, sig))
                dbg(GRE, f"received {p.payload}!!!!\n\n")
                print("No handler found for dmx:", dmx.hex())

    def push(self, pkt_lst, forced=True):
        for pkt in pkt_lst:
            feed = self.repo.get_log(pkt.fid)
            if feed == None: continue
            if not forced and feed.subscription <= 0: continue
            for f in self.faces:
                # print(f"_ enqueue {util.hex(pkt.fid[:20])}.{pkt.seq} @{pkt.wire[:7].hex()}")
                f.enqueue(pkt.wire)
            feed.subscription = 0

    def write_plain_48B(self, fid, buf48, sign=None):
        self.write_typed_48B(fid, buf48, packet.PKTTYPE_plain48, sign)

    def write_typed_48B(self, fid, buf48, typ, sign=None):
        """
        Prepare next log entry, finalise this packet and send it.
        :param fid: feed id (bin encoded)
        :param typ: signature algorithm and packet type
        :param buf48: payload (will be padded)
        :param sign: signing function
        :return: nothing
        """
        feed = self.repo.get_log(fid)
        self.ndlock.acquire()
        if sign is None:
            pkt = feed.write_typed_48B(buf48, typ, lambda msg: self.ks.sign(fid, msg))
        else:
            pkt = feed.write_typed_48B(buf48, typ, sign)
        self.arm_dmx(pkt.dmx) # remove potential old demux handler
        # dbg(GRE, f"DMX OUT: {util.hex(pkt.dmx)} for {util.hex(fid)}")
        self.ndlock.release()

        if self.logs[util.hex(fid)] == LOGTYPE_private: return

        for f in self.faces:
            # print(f"_ enqueue2 {util.hex(pkt.fid[:20])}.{pkt.seq} @{pkt.wire[:7].hex()}")
            f.enqueue(pkt.wire)

    def write_blob_chain(self, fid, buf, sign=None):
        feed = self.repo.get_log(fid)
        self.ndlock.acquire()
        if sign is None:
            pkt, blobs = feed.prepare_chain(buf, lambda msg: self.ks.sign(fid, msg))
        else:
            pkt, blobs = feed.prepare_chain(buf, sign)
        buffer = self.repo.persist_chain(pkt, blobs)[:1]
        self.ndlock.release()

        if self.logs[util.hex(fid)] == LOGTYPE_private: return

        for f in self.faces:
            for p in buffer:
                # dbg(BLU, f"f={f}, pkt={p[:3]}")
                f.enqueue(p)

    # ----------------------------------------------------------------------

    def incoming_want_request(self, demx, buf, neigh):
        """
        Handle want request.

        Called from on_rx, added to self.dmxt in arm_dmx (from arq_loop)
        :param demx: DMX field of excpected packet
        :param buf: packet "as on the wire"
        :param neigh: the corresponding IO interface
        :return: nothing
        """
        print("incoming want")

        lst = bipf.loads(buf[DMX_LEN:])
        if not lst or type(lst) is not list:
            print("error decoding want request")
            return
        if len(lst) < 1 or type(lst[0]) is not int:
            print("error decoding want request with offset")
            return
        offs = lst[0]
        v = "WANT vector=["
        credit = 3
        for i in range(1, len(lst)):
            try:
                ndx = (offs + i - 1) % len(self.goset.keys)
                fid = self.goset.keys[ndx]
                seq = lst[i]
                v += f' {ndx}.{seq}'
            except:
                print("error incoming Want error")
                continue
        while credit > 0:
            log = self.repo.get_log(fid)
            if len(log) < seq:
                break
            pkt = log[seq]
            print("NODE have entry", fid.hex(),".",seq)
            print("entry:",pkt.dmx.hex())
            for f in self.faces:
                f.enqueue(pkt.wire)
            seq += 1
            credit -= 1

        v += " ]"
        print("Node", v)
        if credit == 3:
            print("Node no entry found to serve")
        
        # Little perk for identity.__save_dmxt: calling with an empty buffer
        # returns None, which means we can discard it
        # if buf is None:
        #     return None
        # buf = buf[7:]  # cut the DMX away
        # while len(buf) >= 24:
        #     fid = buf[:32]
        #     seq = int.from_bytes(buf[32:36], 'big')
        #     h = util.hex(fid)[:20]  # idea: seq -= h?
        #     feed = None
        #     try:
        #         feed = self.repo.get_log(fid)
        #         if feed != None:
        #             pkt = feed[seq]
        #             # print(f"_ enqueue3 {util.hex(pkt.fid[:20])}.{pkt.seq} @{pkt.wire[:7].hex()}")
        #             neigh.face.enqueue(pkt.wire)
        #             # dbg(GRA, f'    have {h}.[{seq}], will send {x.hex()[:10]}')
        #     except:
        #         # dbg(GRA, f"    no entry for {h}.[{seq}]")
        #         if feed != None and seq == len(feed) + 1:
        #             feed.subscription += 1
        #         pass
        #     buf = buf[36:]

    def incoming_blob_request(self, demx, buf, neigh):
        # Little perk for identity.__save_dmxt: calling with an empty buffer
        # returns None, which means we can discard it
        # if buf is None:
        #     return None
        # buf = buf[7:]  # cut DMX off
        # while len(buf) >= 22:
        #     hptr = buf[:20]
        #     # Take the first 3 bytes of the header: the last of the chain is only 0s (whole header)
        #     # FIXME : compute count on each iteration?
        #     cnt = int.from_bytes(buf[20:22], 'big')
        #     try:
        #         while cnt > 0:
        #             blob = self.repo.fetch_blob(hptr)
        #             if not blob:
        #                 break
        #             # dbg(GRA, f'    blob {util.hex(hptr)}, will send')
        #             neigh.face.enqueue(blob)
        #             cnt -= 1
        #             hptr = blob[-20:]
        #     except Exception as e:
        #         dbg(RED, e)
        #         # dbg(GRA, f"    no entry for {h}.[{seq}]")
        #         pass
        #     buf = buf[22:]
        print("Node incoming CHNK request")
        vect = bipf.loads(buf[DMX_LEN:])
        if vect == None or type(vect) != list:
            print("Node error decoding CHNK request")
            return
        print(vect)
        v = "CHNK vector=["
        credit = 3
        for e in vect:
            try:
                fNDX = e[0]
                fid = self.goset.keys[fNDX]
                seq = e[1]
                cnr = e[2]
                v += f" {fid.hex()}.{seq}.{cnr}"
            except Exception as e:
                
                print("Node incoming CHNK error")
                print(e)
                continue
                
            pkt = self.repo.get_log(fid)[seq]
            
            if pkt is None or int.from_bytes(pkt.typ) != repository.packet.PKTTYPE_chain20:
                if pkt is None:
                    print("could not find packet")
                continue
            (sz, szlen) = bipf.varint_decode_max(pkt.wire, DMX_LEN + 1, DMX_LEN + 4)
            if(sz <= 28 - szlen):
                continue
            maxChunks = (sz - (28 - szlen) + 99) / 100
            if cnr > maxChunks:
                continue
            while(cnr <= maxChunks and credit > 0):
                credit -= 1
                chunk = self.repo.get_blob(fid, seq, cnr)
                print("CHUNK:", chunk)
                if chunk is None:
                    print("could not find chunk")
                    break
                for f in self.faces:
                    f.enqueue(chunk)
                cnr += 1
        v += " ]"
        print("Node", v)


    def incoming_logentry(self, d, feed, buf, n):
        # Little perk for identity.__save_dmxt: calling with an empty buffer
        # return the feed id that we need to store to recreate the lambda
        print("incoming logentry")
        if buf is None:
            return feed.fid
        pkt = feed.append(buf)  # this invokes the callback
        print("appended")
        self.ndlock.acquire()
        if pkt == None:
            self.ndlock.release()
            return
        assert pkt.fid == feed.fid
        oldfeed = feed
        if not pkt:
            dbg(RED, "    verification failed")
            self.ndlock.release()
            return
        # dbg(GRE, f'  added {pkt.fid.hex()[:20]}:{pkt.seq} {pkt.typ}')
        self.arm_dmx(d)  # remove current DMX handler, request was satisfied
        # FIXME: instead of eager blob request, make this policy-dependent
        if pkt.typ[0] == packet.PKTTYPE_contdas:  # switch feed
            dbg(GRA, f'  told to stop old feed {util.hex(pkt.fid)[:20]}../{pkt.seq}')
            # FIXME: security checks (can this feed still be continued etc)
            newFID = pkt.payload[:32]
            # Redundant with session._process() in callback for instances, do nothing
            feed = self.repo.allocate_log(newFID, 0, newFID[:20])  # install cont.
            if feed is None:
                feed = self.repo.get_log(newFID)
            dbg(GRA, f'  ... and to switch to new feed {util.hex(newFID)[:20]}..')
            # feed.subscription += 1
            # feed.set_append_cb(oldfeed.acb)
            # oldfeed = None
        elif pkt.typ[0] == packet.PKTTYPE_mkchild:
            dbg(GRE, f'  told to create subfeed for {util.hex(pkt.fid)[:20]}../{pkt.seq}')
            # FIXME: security checks (can this feed still be continued etc)
            newFID = pkt.payload[:32]
            newFeed = self.repo.allocate_log(newFID, 0, newFID[:20])  # install cont.
            dbg(GRE, f'    new child is {util.hex(newFID)[:20]}..')
            newFeed.set_append_cb(oldfeed.acb)
            pktdmx = packet._dmx(newFID + int(1).to_bytes(4, 'big') + newFID[:20])
            # dbg(GRA, f"+dmx pkt@{util.hex(pktdmx)} for {util.hex(newFID)[:20]}.[1] /mkchild")
            self.arm_dmx(pktdmx,
                         lambda buf, n: self.incoming_logentry(pktdmx,
                                                               newFeed, buf, n),
                         f"{util.hex(newFID)[:20]}.[1] /mkchild")
            self.request_latest(newFeed, "<<~")
        elif pkt.typ[0] == packet.PKTTYPE_chain20:  # prepare for first blob in chain:
            print("received PKTTYPE_chain20")
            h = util.hex(feed.fid)[:20]
            # FIXME where is the node ('nd') defined? It throws errors
            pkt.undo_chain(lambda h: self.repo.fetch_blob(h))
            #self.request_chain(pkt)
            hptr = pkt.chain_nextptr # is None if log entry doesn't contain a chain
            if hptr:
                self.pending_chains[hptr] = (feed.fid, pkt.seq, 0)
                self.persist_pending()
                self.arm_blob(hptr, lambda buf: self.incoming_chainedblob(buf,feed.fid,pkt.seq,0))
        # elif pkt.typ[0] == packet.PKTTYPE_iscontn:
        #     if pkt.seq == 1: # first packet has proof, don't invoke the cb
        #         oldfeed = None
        seq, prevhash = feed.getfront()
        seq += 1
        nextseq = seq.to_bytes(4, 'big')
        pktdmx = packet._dmx(feed.fid + nextseq + prevhash)
        # dbg(GRA, f"+dmx pkt@{util.hex(pktdmx)} for {util.hex(feed.fid)[:20]}.[{seq}] /incoming")
        self.arm_dmx(pktdmx,
                     lambda buf, n: self.incoming_logentry(pktdmx,
                                                           feed, buf, n),
                     f"{util.hex(feed.fid)[:20]}.[{seq}] /incoming")
        # set timeout to 1sec more than production interval
        self.next_timeout[0] = time.time() + 6
        self.ndlock.release()

    def incoming_chainedblob(self, buf: bytearray, fid: bytearray, seq: int, blbt_ndx: int) -> None:
        
        print("INCOMING BLOB")
        if len(buf) != 120: return
        # dbg(GRA, f"RCV blob@dmx={util.hex(h)} / chained")
        self.repo.add_blob(buf)
        hptr = buf[-20:]
        prev = packet.blob2hashptr(buf)
        self.arm_blob(prev)  # remove current blob handler, expected blob was received
        if prev in self.pending_chains:
            del self.pending_chains[prev]
            self.persist_pending()
        if hptr != bytes(20):
            # rearm a blob handler for the next blob in the chain:
            # dbg(GRA, f"    awaiting next blob {util.hex(hptr)}")
            # cnt -= 1
            # if cnt == 0:  # aks for next batch of blob
            #     d = packet._dmx(b'blobs')
            #     wire = d + hptr + int(4).to_bytes(2, 'big')
            #     for f in self.faces:
            #         f.enqueue(wire)
            #         # dbg(GRA, f"SND blob chain request to dmx={d.hex()} for {hptr.hex()}")
            #     cnt = 4
            # self.arm_blob(hptr,
            #               lambda buf, n: self.incoming_chainedblob(cnt, hptr, buf, n))
            self.pending_chains[hptr] = (fid, seq, blbt_ndx + 1)
            self.persist_pending()
            self.arm_blob(hptr, lambda buf: self.incoming_chainedblob(buf,fid,seq,blbt_ndx + 1))
        else:
            print("IS complete?")
            log = self.repo.get_log(fid)
            pkt = log[seq]
            pkt.undo_chain(lambda h: self.repo.fetch_blob(h))
            if pkt.content_is_complete():
                print("Complete --> callback")
                log.acb(pkt)
            # dbg(GRA, f"    end of chain was reached")
            pass
            

    def request_latest(self, feed, comment="?"):
        """
        request the latest packet for a given feed
        :param feed: instance of LOG
        :param comment: Optional comment to be included in the request
        :return: nothing
        """
        if self.logs.get(util.hex(feed.fid)) is None:
            dbg(GRE, "Oh shit")
        if self.logs.get(util.hex(feed.fid)) != LOGTYPE_remote:
            # if len(self.my_logs.intersection(feed.fid)) == 0:
            return
        # dbg(GRE, f"in request latest for {comment}: !!!!!!!!!!{self.logs.get(util.hex(feed.fid))}")

        seq, prevhash = feed.getfront()
        seq += 1
        nextseq = seq.to_bytes(4, 'big')
        pktdmx = packet._dmx(feed.fid + nextseq + prevhash)
        # dbg(GRA, f"+dmx pkt@{util.hex(pktdmx)} for {util.hex(feed.fid)[:20]}.[{seq}]")
        # dbg(RED, f"{comment} for {util.hex(feed.fid)[:20]}.[{seq}]")
        self.arm_dmx(pktdmx,
                     lambda buf, n: self.incoming_logentry(pktdmx,
                                                           feed, buf, n),
                     comment + f"{util.hex(feed.fid)[:20]}.[{seq}])")

        for p in self.logs:
            p = util.fromhex(p)
            want_dmx = packet._dmx(p + b'want')
            print("send want_dmx:", util.hex(want_dmx))
            wire = want_dmx + feed.fid + nextseq
            # does not need padding to 120B, it's not a log entry or blob
            d = util.hex(want_dmx)
            h = util.hex(feed.fid)[:20]
            for f in self.faces:
                f.enqueue(wire)
                # dbg(GRA, f"SND {len(wire)} want request to dmx={d} for {h}.[{seq}]")

    # def request_chain(self, pkt):
    #     # dbg(YEL, "request_chain", util.hex(pkt.fid)[:8], pkt.seq,
    #     #       util.hex(pkt.chain_nextptr) if pkt.chain_nextptr else None)
    #     hptr = pkt.chain_nextptr
    #     if hptr == None: return
    #     # dbg(GRA, f"+blob @{util.hex(hptr)}")
    #     self.arm_blob(hptr,
    #                   lambda buf, n: self.incoming_chainedblob(4, hptr, buf, n))
    #     d = packet._dmx(b'blobs')
    #     wire = d + hptr + int(4).to_bytes(2, 'big')
    #     for f in self.faces:
    #         f.enqueue(wire)
    #         # dbg(GRA, f"SND blob chain request to dmx={d.hex()} for {hptr.hex()}")

    def arq_loop(self):  # Automatic Repeat reQuest
        # dbg(GRA, f"This is Replication for node {util.hex(self.myFeed.fid)[:20]}")
        # prepare to serve incoming requests for logs I have
        # i.e., sent to me, which means with DMX="myFID want"

        # dbg(GRA, f"+dmx want@{util.hex(want_dmx)} / me {util.hex(self.me)[:20]}...")
        # for fid in self.logs:
        #     if self.logs[fid] != LOGTYPE_remote:
        #         want_dmx = packet._dmx(util.fromhex(fid) + b'want')
        #         self.arm_dmx(want_dmx,
        #         lambda buf, n: self.incoming_want_request(want_dmx, buf, n), f"arq to me {fid[:20]}")
        while True:
            v = ""
            vect = []
            encoding_len = 0
            self.log_offs = (self.log_offs + 1) % len(self.goset.keys)
            vect.append(self.log_offs)
            i = 0
            while i < len(self.goset.keys):
                ndx = (self.log_offs + i) % len(self.goset.keys)
                key = self.goset.keys[ndx]
                feed = self.repo.get_log(key)
                bptr = feed.frontS + 1
                vect.append(bptr)

                dmx = packet._dmx(key + bptr.to_bytes(4, 'big') + feed.frontM)
                # print("arm", dmx.hex(), f"for {key.hex()}.{bptr}")
                self.arm_dmx(dmx, lambda buf, n: self.incoming_logentry(dmx,
                                                            feed, buf, n))
                v += ("[ " if len(v) == 0 else ", ") + f'{ndx}.{bptr}'
                i += 1
                encoding_len += len(bipf.dumps(bptr))
                if encoding_len > 100:
                    break

            self.log_offs = (self.log_offs + i) % len(self.goset.keys)
            if len(vect) > 1:
                wire = self.want_dmx + bipf.dumps(vect)
                for f in self.faces:
                    f.enqueue(wire)
            # print(">> sent WANT request", v, "]")

            chunk_req_list = []
            for c in self.pending_chains:
                fid, seq, blbt_ndx = self.pending_chains[c]
                fid_nr = next(i for i, x in enumerate(self.goset.keys) if util.byteArrayCmp(x, fid) == 0)
                chunk_req_list.append([fid_nr, seq, blbt_ndx])

            if chunk_req_list:
                wire = self.chnk_dmx + bipf.dumps(chunk_req_list)
                for f in self.faces:
                    f.enqueue(wire)
                    print(">> sent CHK request:", chunk_req_list)
            # data = b'Trying to reach back'
            # data += bytes(48 - len(data))
            # print(f"Sending try: {data}")
            # self.write_plain_48B(self.me, data)
            time.sleep(5)  # TODO: back to 5


        
        # # prepare to serve blob requests
        # blob_dmx = packet._dmx(b'blobs')
        # # dbg(GRA, f"+dmx blob@{util.hex(blob_dmx)}")
        # self.arm_dmx(blob_dmx,
        #              lambda buf, n: self.incoming_blob_request(blob_dmx, buf, n), "init blobs")
        # while True:  # periodic ARQ
        #     now = time.time()
        #     if self.next_timeout[0] < now:

        #         self.ndlock.acquire()
        #         for fid in self.logs:
        #             feed = self.repo.get_log(util.fromhex(fid))
        #             if self.logs[fid] != LOGTYPE_remote or feed is None:
        #                 continue
        #             if feed[-1].typ[0] == packet.PKTTYPE_contdas:
        #                 # this is a terminated feed, don't ask for news
        #                 continue
        #             self.request_latest(feed, "arq for logs")
        #         self.ndlock.release()

        #         rm = []
        #         for pkt in self.pending_chains:
        #             pkt.undo_chain(lambda h: self.repo.fetch_blob(h))
        #             if pkt.content_is_complete():
        #                 rm.append(pkt)
        #             else:  # FIXME: should have a max retry count
        #                 self.request_chain(pkt)
        #         for r in rm:
        #             self.pending_chains.remove(pkt)
        #         self.next_timeout[0] = now + 1
        #         time.sleep(2)
        #     else:
        #         time.sleep(self.next_timeout[0] - now)

    def set_want_dmx(self, goset_state: bytearray) -> None:
        

        if self.want_dmx:
            self.arm_dmx(self.want_dmx, None, None)
        
        if self.chnk_dmx:
            self.arm_dmx(self.chnk_dmx, None, None)

        self.want_dmx = self.compute_dmx('want'.encode('utf-8') + self.goset.state)
        self.chnk_dmx = self.compute_dmx('blob'.encode('utf-8') + self.goset.state)
        print("NODE set_want_dmx(): set new dmx to", self.want_dmx.hex())
        self.arm_dmx(self.want_dmx, lambda buf, n: self.incoming_want_request(self.want_dmx, buf, n))
        self.arm_dmx(self.chnk_dmx, lambda buf, n: self.incoming_blob_request(self.chnk_dmx, buf, n), "init blobs")


    def compute_dmx(self, buf: bytearray) -> bytearray:
        return hashlib.sha256(DMX_PFX + buf).digest()[:DMX_LEN]
    
    # persist missing chain (for restart)
    def persist_pending(self):
        print("current pending:", self.pending_chains)
        _, name = self.ks.kv[self.me]
        path = util.DATA_FOLDER + name + '/_backed/pending_chains.json'
        # json doesn't support tuples or bytes
        j = {}
        for c in self.pending_chains:
            fid, seq, blbt_ndx = self.pending_chains[c]
            j[c.hex()] = [fid.hex(), seq, blbt_ndx]

        print(j)
        with open(path, 'w+') as f:
            f.write(json.dumps(j))


# eof
