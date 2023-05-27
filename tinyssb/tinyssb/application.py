# tinyssb/application.py
# 2022-05-30 <et.mettaz@unibas.ch>

"""
__app__ = [
    'create_inst',
    'add_member',
    'update_remote_instance_feed',
    'resume_inst',
    'replay',
    'close_inst',
    'terminate_inst',
    'delete_inst',
    'send',
    'set_callback',
    'update_inst'
]
"""

import bipf
from . import packet, util
from .dbg import GRE, dbg
from .exception import *
from .node import LOGTYPE_public, LOGTYPE_remote
from .session import SlidingWindow

class Application:

    def __init__(self, log_manager, log, appID):
        self.manager = log_manager
        self.appID = appID
        self.window = None
        self.callback = None
        self.instances = {}
        self.log = log
        self.next_inst_id = 0

        self.__load_instances()

    def create_inst(self, members=None, name=None, created=None):
        """
        Create a new instance (game).
        Returns the instance id (as a string).
        """
        # 1.0 (public), 2.1, 3.0, _, 4.1
        while self.instances.get(str(self.next_inst_id)) is not None:
            self.next_inst_id += 1
        dbg(GRE, f"Create instance with {members}")
        # 1.0
        fid = self.manager.create_on_disk(self.log.fid, self.next_inst_id, LOGTYPE_public)

        # 3.0
        if name is None:
            name = f"me ({str(self.next_inst_id)})"
        peer = { 'id': self.next_inst_id, 'il': fid, 'l': fid, 'n': name }
        self.manager.set_in_log(self.log.fid, bipf.dumps(peer))

        # 2.1
        ret = str(peer.pop('id'))
        peer['m'] = {}
        self.instances[ret] = peer
        members_id = []
        if members is not None:
            for m in members:
                mid = self.manager.identity.directory['aliases'].get(m)
                members_id.append(mid)
                self.add_member(ret, None, mid)

        # 4.1
        self.window = SlidingWindow(self, self.manager, self.next_inst_id, fid, self.callback)

        self.next_inst_id += 1

        # 5.0
        if members_id:
            if created is None:
                # a = appID, c = create (fid of the feed for this group), m = list of members (public keys)
                create = { 'a': self.appID, 'c': fid, 'm': members_id }
                self.manager.write_to_public(bipf.dumps(create))
            else:
                # a = appID, c = created (fid of the feed of the creator for this group), x = accept (fid of locally created feed)
                accept = { 'a': self.appID, 'c': created, 'x': fid }
                self.manager.write_to_public(bipf.dumps(accept))
        return ret

    def add_member(self, inst_id, remote_fid, public_id):
        """
        Add a member to the current group
        :param inst_id: instance id
        :param remote_fid: feed id for this instance
        :param public_id: the fid of his 'public' log
        :return:
        """
        if self.instances.get(str(inst_id)) is None:
            raise NotFoundTinyException(f"There is no instance with id = {inst_id}")
        if public_id is None:
            raise NullTinyException("Public fid of remote peer is None")
        name = self.manager.identity.get_contact_alias(public_id)
        if name is None:
            raise TinyException("Remote was not found in contact list, not added")
        # Check that the contact is not already in the group
        hex_with = util.hex(public_id)
        for tmp in self.instances[str(inst_id)].get('m'):
            if tmp == hex_with:
                raise AlreadyUsedTinyException("Peer is already a member of the instance")

        # 2.1
        inst_name = f"{name}, " + self.instances[str(inst_id)]['n']
        self.instances[str(inst_id)]['n'] = inst_name

        self.instances[str(inst_id)]['m'][util.hex(public_id)] = { 'r': None, 'ir': None }
        if remote_fid is None:
            update = { 'id': str(inst_id), 'n': inst_name, 'm': public_id, 'r': None }
        else:
            update = { 'id': str(inst_id), 'n': inst_name }
            self.update_remote_instance_feed(inst_id, remote_fid, public_id)

        # 3.0
        self.manager.set_in_log(self.log.fid, bipf.dumps(update))

    def update_remote_instance_feed(self, inst_id, remote_fid, public_id):
        """
        Change the feed of a remote member
        :param inst_id: instance id number
        :param remote_fid: new instance fid of the remote member
        :param public_id: public fid of the remote member
        :return:
        """
        # 1.2, 2.1, 3.0, 4.1, 5.1
        if self.instances.get(str(inst_id)) is None:
            raise NotFoundTinyException(f"There is no instance with id = {inst_id}")
        if public_id is None:
            raise NullTinyException("Public fid of remote peer is None")

        # Not adding a member but updating its feed id
        hex_with = util.hex(public_id)
        for tmp in self.instances[str(inst_id)].get('m'):
            if tmp == hex_with:
                # 1.2
                self.manager.allocate_for_remote(remote_fid, public_id)

                # 4.1
                if self.window and self.window.id_number == inst_id:
                    self.window.add_remote(remote_fid)
                    self.window.start()

                # 2.1
                if self.instances[str(inst_id)]['m'][hex_with].get('ir') is None:
                    self.instances[str(inst_id)]['m'][hex_with]['ir'] = remote_fid
                self.instances[str(inst_id)]['m'][hex_with]['r'] = remote_fid

                # 3.0
                update = { 'id': str(inst_id), 'm': public_id, 'r': remote_fid }
                self.manager.set_in_log(self.log.fid, bipf.dumps(update))
                return  # updated remote log
        raise NotFoundTinyException("Contact is not a member of the instance yet")

    def resume_inst(self, inst_id):
        """ Load and start a game/instance """
        # _, _, _, 4,1
        # 1.1 and 2.1 are taken care of in __load_inst
        if self.window is not None and self.window.id_number != inst_id:
            self.window.close()
            self.window = None
        if self.window is None or self.window.id_number != inst_id:
            inst = self.instances.get(str(inst_id))
            if inst is None:
                raise NotFoundTinyException(f"There is no instance with id = {inst_id}")
            self.window = SlidingWindow(self, self.manager, inst_id, inst['l'], self.callback)
            for remote in inst.get('m'):
                self.window.add_remote(inst['m'][remote].get('r'))
        self.window.start()

    def replay(self):
        if not self.window:
            raise NullTinyException("No instance is running")
        inst = self.instances.get(str(self.window.id_number))
        ir_list = []
        for r in inst.get('m'):
            ir_list.append(inst['m'][r].get('ir'))
        self.window.replay(inst['il'], ir_list)

    def close_inst(self, inst_id):
        """
        Close a game or instance.
        It can later be normally resumed with resume_inst()
        """
        # _, _, _, 4.1, _
        if self.instances.get(str(inst_id)) is None:
            raise NotFoundTinyException(f"There is no instance with id = {inst_id}")

        # 4.1
        if self.window and self.window.id_number == inst_id:
            self.window.close()
        self.window = None

    def terminate_inst(self, inst_id):
        """
        Terminate a game or instance (write a final 'end_of_file' message)
        Keep the data on disk as well as the inst in self.instances
        """
        # _, _, _, 4.1, 5.2
        self.close_inst(inst_id)

        # 5.2
        fid = self.instances[str(inst_id)]['il']
        self.manager.write_eof(fid)

    def delete_inst(self, inst_id):
        """
        Delete an instance and erase its data on disk
        """
        # 1.3, 2.1, 3.1, _ + terminate_inst

        self.terminate_inst(inst_id)

        # 2.1
        i = self.instances.pop(str(inst_id))

        # 1.3 and 3.1
        self.manager.delete_on_disk(i['il'], self.log.fid, bipf.dumps({ 'id': inst_id }))

    def send(self, msg):
        """ Send data to the other participant by writing in the local feed """
        if self.window is not None and not self.window.started:
            self.window.start()
        self.window.write(msg)

    def set_callback(self, callback):
        """ Set callback for received messages """
        self.callback = callback
        if self.window is not None:
            self.window.set_callback(callback)

    def update_inst(self, inst_id, name, local_fid=None):
        """
        Update the name or local feed id
        """
        # _, 2.1, 3.0, 4.1
        inst = self.instances.get(str(inst_id))
        if inst is None:
            raise NotFoundTinyException(f"There is no instance with id = {inst_id}")

        # 2.1
        p = { 'id': inst_id }
        if local_fid is not None:
            p['l'] = local_fid
            inst['l'] = local_fid
        if name is not None:
            p['n'] = name
            inst['n'] = name

        # 3.0
        self.manager.set_in_log(self.log.fid, bipf.dumps(p))

    def _update_inst_with_old_remote(self, inst_id, new_remote_fid, old_remote_fid):
        """
        Update the remote fid of an instance.
        To use if one has the old remote fid but not the public id ('public_id').
        """
        if self.instances.get(str(inst_id)) is None:
            raise NotFoundTinyException(f"There is no instance with id = {inst_id}")
        if new_remote_fid is None:
            raise NullTinyException("new_remote_fid is null")
        peer = self.instances[str(inst_id)].get('m')
        for tmp in peer:
            if peer[tmp]['r'] == old_remote_fid or peer[tmp]['ir'] == old_remote_fid:
                self.update_remote_instance_feed(inst_id, new_remote_fid, util.fromhex(tmp))
                return
        raise TinyException("old_remote_fid is not found")

    def __load_instances(self):
        # 1.1, 2.1, _, _, _
        for i in range(1, len(self.log)+1):
            pkt = self.log[i]
            if pkt.typ[0] == packet.PKTTYPE_delete:
                inst_id = bipf.loads(pkt.payload)['id']
                out = self.instances.pop(inst_id)
                self.manager.deactivate_log(out['l'])
                for rem in out['m']:
                    self.manager.deactivate_log(out['m'][rem]['r'])
            elif pkt.typ[0] == packet.PKTTYPE_set:
                self.__extract_instance(bipf.loads(pkt.payload))
            elif pkt.typ[0] == packet.PKTTYPE_chain20:
                pkt.undo_chain(self.manager.get_blob_function())
                self.__extract_instance(bipf.loads(pkt.chain_content))

    def __extract_instance(self, payload):
        inst_id = str(payload['id'])
        if self.instances.get(inst_id) is None:
            # first entry for an inst must contain id and initial local feed
            self.instances[inst_id] = { 'il': payload.get('il'), 'l': payload.get('l'), 'm': {}}
            self.manager.activate_log(payload.get('l'), LOGTYPE_public)

        if payload.get('m') is not None:
            hex_with = util.hex(payload['m'])
            if self.instances[inst_id].get('m') is None:
                self.instances[inst_id]['m'] = {}
            if payload.get('r') is None:
                if self.instances[inst_id]['m'].get(hex_with) is None:
                    self.instances[inst_id]['m'][hex_with] = { 'r': None, 'ir': None }
            elif self.instances[inst_id]['m'].get(hex_with) is None:
                self.instances[inst_id]['m'][hex_with] = { 'r': payload.get('r'), 'ir': payload.get('r') }
                self.manager.activate_log(payload['r'], LOGTYPE_remote)
            else:
                tmp = self.instances[inst_id]['m'][hex_with]
                if tmp.get('ir') is None:
                    tmp['ir'] = payload['r']
                else:
                    self.manager.deactivate_log(tmp['ir'])
                tmp['r'] = payload['r']
                self.manager.activate_log(payload['r'], LOGTYPE_remote)

        tmp = payload.get('l')
        if tmp is not None:
            self.instances[inst_id]['l'] = tmp
            self.manager.activate_log(tmp, LOGTYPE_public)

        tmp = payload.get('n')
        if tmp is not None:
            self.instances[inst_id]['n'] = tmp
# eof
