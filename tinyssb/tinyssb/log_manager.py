# tinyssb/log_manager.py
# 2022-05-30 <et.mettaz@unibas.ch>
import _thread
import json
import os

import bipf
from tinyssb import packet, util, application
from tinyssb.dbg import *
from tinyssb.exception import *
from tinyssb.node import LOGTYPE_private, LOGTYPE_public, LOGTYPE_remote

class LogManager:

    def __init__(self, identity, node, default_logs):
        self.identity = identity
        self.node = node
        self.node.activate_log(default_logs['aliases'], LOGTYPE_private)
        self.node.activate_log(default_logs['apps'], LOGTYPE_private)
        self.node.activate_log(default_logs['public'], LOGTYPE_public)

        self.__save_key_lock = _thread.allocate_lock()

    def activate_log(self, fid, typ):
        """
        Keeps track of all the active private, public and remote feeds
        """
        self.node.activate_log(fid, typ)

    def deactivate_log(self, fid):
        self.node.deactivate_log(fid)

    def create_on_disk(self, parent_log_id, name, log_type): # 1.0
        """
        Create a new fid in disk
        :param parent_log_id: feed id of the feed where the make_child will be written
        :param name: the name of the new fid
        :param log_type: type of the fid (see add_log)
        :return: feed id of the new fid
        """
        assert log_type in [LOGTYPE_private, LOGTYPE_public]
        assert bipf.encodingLength(name) < 48  # Must fit in 48B for 'delete'

        fid = self.node.ks.new(name)
        n = bipf.dumps(name)
        n += bytes(max(16 - len(n), 0))
        packets = self.node.repo.mk_child_log(parent_log_id,
                            self.node.ks.get_signFct(parent_log_id), fid,
                            self.node.ks.get_signFct(fid), n)

        if log_type == LOGTYPE_public:
            self.node.push(packets)
        self.node.activate_log(fid, log_type)
        self.__save_keys()
        return fid

    def allocate_for_remote(self, fid, public_fid=bytes(32)): # 1.2
        """
        Allocate disk space for a remote feed we start following.
        The public_fid lets us find which peers write to this feed, allowing
        an easy search in the contact list
        :param fid: remote feed id
        :param public_fid: feed id of the "public" feed for this remote
        """
        self.node.repo.allocate_log(fid, 0, fid[:20], None, public_fid)
        self.node.activate_log(fid, LOGTYPE_remote)

    def delete_on_disk(self, fid, parent_fid, data, all_feeds=True): # 1.3 (includes 3.1)
        """
        Delete all data associated with a feed.
        Automatically deactivate the log from the list in node.py and write a
        "delete" message in the parent feed.
        If all_feeds is set to "True", this will not only delete the given feed,
        but also all continuation feeds from that point (but not an eventual
        preceding feed or child feed).
        Also delete the key pair (for local feeds only)
        :param fid: the feed id of the log to be deleted
        :param parent_fid: the feed id of the log containing the ADT that contained the feed
        :param data: the data to write in the payload of the "delete" packet
        :param all_feeds: if False, only deletes one feed (no continuation feed)
        """
        log = self.get_log(fid)
        if log is None:
            dbg(YEL, f"Delete all: there is no log with fid = {util.hex(fid)}")
            return
        pkt = log[log.frontS]
        self.node.repo.del_log(log.fid)
        try: self.node.ks.remove(log.fid)
        except KeyError: pass  # remote log, we do not have the keys
        if pkt.typ[0] == packet.PKTTYPE_contdas and pkt.payload[:32] != bytes(32) and all_feeds:
            self.delete_on_disk(pkt.payload[:32], parent_fid, data)

        self.delete_in_log(parent_fid, data)
        self.node.deactivate_log(fid)
        del log

    def delete_one_log(self, fid):
        """ Delete one log (after a continuation packet for example) """
        log = self.get_log(fid)
        if log is None:
            dbg(YEL, f"Delete one: there is no log with fid = {util.hex(fid)}")
            return
        self.node.repo.del_log(log.fid)
        try: self.node.ks.remove(log.fid)
        except KeyError: pass  # remote log, we do not have the keys

        self.node.deactivate_log(fid)
        del log

    def set_in_log(self, fid, data): # 3.0
        """
        Set a value in a log.
        The data must be of type byte array (bipf.dumps() of bytes()),
        but can be of arbitrary length (will be padded in write_in_log)
        :param fid: feed id of the log to write to
        :param data: byte array, the value to set
        """
        assert self.node.logs[util.hex(fid)] == LOGTYPE_private
        self.write_in_log(fid, data, packet.PKTTYPE_set)

    def delete_in_log(self, fid, data): # 3.1
        """
        Delete a value in a log.
        Append-only log does not allow for deletion, this just writes in the log
        that the element os no longer included in the Abstract Data Type formed by the feed
        :param fid: feed id containing the ADT
        :param data: the data to write in the payload
        """
        assert self.node.logs[util.hex(fid)] == LOGTYPE_private
        self.write_in_log(fid, data, packet.PKTTYPE_delete)

    def write_in_log(self, fid, data, typ=packet.PKTTYPE_plain48): # 5.0
        """
        Write a packet in a fid
        :param fid: feed id of the fid to write to
        :param data: the data to write (string)
        :param typ: the type of the packet
        """
        if type(data) is str:
            data = bipf.dumps(data)
        if len(data) > 48:
            self.node.write_blob_chain(fid, data)
        else:
            data += bytes(48 - len(data))
            self.node.write_typed_48B(fid, data, typ)

    def write_to_public(self, data):
        self.write_in_log(self.identity.public, data)

    def add_remote(self, fid): # 5.1
        pass

    def write_eof(self, fid): # 5.2
        """
        Append an end_of_file packet to the feed.
        This closes the feed (but do not delete it)
        :param fid:
        :return:
        """
        self.node.write_typed_48B(fid, bytes(48), packet.PKTTYPE_contdas)

    def create_continuation_log(self, local_fid):
        """
        Create a continuation feed on disk for the local instance Log
        :param local_fid: the current (deprecated) feed id
        :return: the new feed id
        """
        dbg(GRA, f"SESS: ending feed {util.hex(local_fid)[:20]}..")
        new_key = self.node.ks.new('continuation')
        new_sign = lambda msg: self.node.ks.sign(new_key, msg)
        packets = self.node.repo.mk_continuation_log(local_fid,
            lambda msg: self.node.ks.sign(local_fid, msg),
            new_key, new_sign)

        self.deactivate_log(local_fid)
        self.activate_log(packets[1].fid, LOGTYPE_public)
        self.node.arm_dmx(packets[0].dmx)
        self.node.push(packets)
        return self.get_log(packets[1].fid)

    def get_blob_function(self):
        return lambda h: self.node.repo.fetch_blob(h)

    def get_log(self, fid):
        return self.node.repo.get_log(fid)

    def get_contact_fid(self, fid):
        """ Get the fid of the public feed using the given feed"""
        log = self.get_log(fid)
        return log.parfid

    def get_log_type(self, fid):
        try:
            return self.node.logs[util.hex(fid)]
        except KeyError: return None

    def get_contact_alias(self, public_key):
        """
        Get the human-readable alias name
        :param public_key: the public key (byte array)
        :return:
        """
        return self.identity.get_contact_alias(public_key)

    def public_cb(self, in_pkt):
        """
        Handle incoming packet in other peers' public feed.
        Wait for the whole data in case of blob
        :param in_pkt: incoming packet
        """
        _thread.start_new_thread(lambda: self.__public_cb(in_pkt), tuple())

    def __public_cb(self, pkt):
        if pkt.typ[0] > 1:
            return
        try:
            if pkt.typ[0] == packet.PKTTYPE_chain20:
                while not pkt.undo_chain(self.get_blob_function()):
                    time.sleep(0.2)
            rx = bipf.loads(pkt.get_content())

            for app_name in self.identity.directory['apps']:
                # Check that I have this app installed (with appID)
                if rx.get("a") == self.identity.directory['apps'][app_name].get('appID'):
                    if rx.get("m") is not None:
                        # This is a "create" request
                        self.__add_inst(rx, app_name, pkt)
                    else:
                        assert rx.get("x") is not None
                        self.__find_inst_accepted_remote(rx, app_name, pkt)

        except Exception as err:
            dbg(ERR, f"failed to decode...: {err}")

    def __find_inst_accepted_remote(self, rx, app_name, pkt):
        log = self.get_log(self.identity.directory['apps'][app_name]['fid'])
        app = application.Application(self, log, self.identity.directory['apps'][app_name]['appID'])
        created = rx.get('c')
        for i in app.instances:
            if app.instances[i].get('il') == created or app.instances[i].get('l') == created:
                app.update_remote_instance_feed(i, rx.get('x'), pkt.fid)
                return
            for m in app.instances[i].get('m'):
                if app.instances[i]['m'][m].get('ir') == created or app.instances[i]['m'][m].get('r') == created:
                    app.update_remote_instance_feed(i, rx.get('x'), pkt.fid)
                    return

        raise NotFoundTinyException("Could not find a corresponding instance") # to delete, happens for messages not for us

    def __add_inst(self, rx, app_name, pkt):
        if self.identity.public not in rx.get("m"):
            return  # I'm not part of this group
        log = self.get_log(self.identity.directory['apps'][app_name]['fid'])
        app = application.Application(self, log, self.identity.directory['apps'][app_name]['appID'])

        try:
            creator = self.get_contact_alias(pkt.fid)
            m_aliases = [creator]
            for m in rx.get("m"):
                if m == self.identity.public:
                    continue
                al = self.get_contact_alias(m)
                if al is None:
                    al = creator + "_f_" + util.hex(m)[:4]
                    self.identity.follow(m, al)
                m_aliases.append(al)

            if rx.get('c') is not None:
                inst_id = app.create_inst(m_aliases, None, rx.get('c'))
                app.update_remote_instance_feed(inst_id, rx.get('c'), pkt.fid)
        except AlreadyUsedTinyException as er:
            dbg(ERR, f"Add_app: failed to decode...: {er}")

    def __save_keys(self):
        """
        Flushes the keystore into disk for backup
        For security, saves it in a secondary file,
        then overrides the old version
        """
        file_path = util.DATA_FOLDER + self.identity.name + '/_backed/' + util.hex(self.node.me)
        self.__save_key_lock.acquire()
        self.node.ks.dump(file_path + ".part")

        try:
            os.system(f"mv {file_path}.part {file_path}")
        except Exception as ex:
            dbg(GRE, f"Problem in save_keys: {ex}")
        self.__save_key_lock.release()
        # dbg(BLU, f"Keys are saved")

    def __save_dmxt(self):
        """
        Saves all currently expected dmx to quickly restart later.
        For security, saves them in a secondary file,
        then overrides the old version
        :return the saved dmx:
        """
        dmx = {}
        for d in self.node.dmxt.keys():
            val = self.node.dmxt[d](None, None)
            if val is not None:
                dmx[util.hex(d)] = util.hex(val)
        prefix = f"{util.DATA_FOLDER}{self.identity.name}/_backed/"

        with open(prefix + "dmxt.json.part", "w") as f:
            f.write(util.json_pp(dmx))
        os.system(f"mv {prefix}dmxt.json.part {prefix}dmxt.json")
        return util.json_pp(dmx)

    def __load_dmxt(self):
        try:
            with open(f"{util.DATA_FOLDER}{self.identity.name}/_backed/dmxt.json", "r") as f:
                dmx = json.load(f)
        except FileNotFoundError:
            return # no dmx was saved
        for d, v in dmx.items():
            d = util.fromhex(d)
            feed = self.node.repo.get_log(util.fromhex(v))
            if feed is None:
                raise NotFoundTinyException(f"No feed for {v} ({util.fromhex(v)}): {self.node.repo.listlog()}")
            self.node.arm_dmx(d,
                lambda buf, n: self.node.incoming_logentry(d, feed, buf, n),
                "Reload dmx")

    def loop(self):
        self.node.start()
        self.__save_keys()

        while True:
            time.sleep(1)
            self.__save_dmxt()
            self.__save_keys()
        pass
# eof

"""
Action for logs:

We have 3 types of logs:
- local, private fid ('root', 'aliases', 'apps', "chess", "chat" etc)
- local, public fid ('public', instance '0' of "chess", inst '2' of "chat", etc)
- remote fid (public logs from another peer)

NB: The root fid is a bit special because we do not keep a live trace of it as we
hardly use it at runtime.

For each fid, we have to take care of different aspects:
- the state on the disk, divided in 2 parts:
    - when created (on disk)
        1.0 creating a local fid
        1.1 allocating space for a remote fid
    3.0 when updated
    1.2 when loaded after restart
- the live trace of the state, in id.directory or app.instances
- possible communication, depending on the type:
    - sending new messages (public local)
    - receiving new messages (remote)
    - none (private local) [this needs to be enforced]
- In addition, some logs are used for current activities and are link to an 
    object of a class:
    - Application for the current app
    - SlidingWindow for the current instance (with one to many logs, one being local)

We want here to describe the successive operations needed when adding, loading or removing data
from the disk or live usage. We keep traces on different states on:

- disk
- runtime list of application and app instances available as well as pointers to the current app and instance 
- list of all logs with log type in node.py
- remote peers (data to send through the network)
- pointers to the current app (in identity.py) and instance (in application.py) 

For modularity and correctness, we decided to delegate most of those operations to the log_manager.py.
Operations 1.* (except 1.1), 3.* and 5.* are done in the `log manager`.
We describe here those different actions. The number codes are used in the files directly. 

- disk management at the beginning
    1.0 create on disk
    1.1 load from disk
    1.2 allocate disk for remote
    1.3 delete on disk
- runtime trace of 
    2.0 all apps and aliases in id.directory
    2.1 all instances of running app in application.instances
- updating app or instance state on disk
    3.0 set data on disk (with a 'set' or packet) [in the parent fid, which is private]
    3.1 delete data on disk (with a 'delete' packet) [in the parent fid, which is private]
- management of the current state
    4.0 current app in identity
    4.1 current instance in application
- network communication
    5.0 write a packet in local fid (disk) and propagate it
    5.1 add callback for the reception of a packet from remote
    5.2 write and end_of_file packet on disk and propagate it

Each call to an operation 1.* (including 1.1) is followed by an `activate_log()` or `deactivate_log()`. This allows
us to keep a live trace of all logs in the file system, including their log type, which allows for a 
fast switch from different applications or instances.


Each fid should be tackled by one of the 1.x function every time
TinySSB is launched except the app subfeeds that have to be tackled 
when the app is launched / created. In addition, it must record its
type (public/private/remote) in Node.logs

"""
# eof
