# tinyssb/identity.py

"""
__all__ = [
    'follow',
    'rename',
    'unfollow',
    'get_contact_alias',
    'resume_app',
    'define_app',
    'delete_app',
    'write_to_public'
]
"""
import _thread
import time

import bipf
from . import packet, application, log_manager
from .exception import *
from .node import LOGTYPE_private, LOGTYPE_remote

class Identity:

    def __init__(self, root, name, default_logs=None):
        self.name = name
        self.manager = log_manager.LogManager(self, root, default_logs)

        self.aliases = default_logs['aliases']
        self.public = default_logs['public']
        self.apps = default_logs['apps']
        self.directory = {'apps': {}, 'aliases': {}}

        self.__current_app = None

        self.__load_contacts()
        self.__load_apps()
        _thread.start_new_thread(self.manager.loop, tuple())

    def follow(self, public_key, alias):
        """
        Subscribe to the feed with the given pk.

        If the public key is already in the contact list, update the name to
        the given key
        :param public_key: bin encoded feedID
        :param alias: name to give to the peer
        :return: True if succeeded (if alias and public key were not yet in db)
        """
        # 1.2, 2.0, 3.0, _, 5.1
        if self.directory['aliases'].get(alias):
            if self.directory['aliases'][alias] == public_key:
                return  # already following
            raise AlreadyUsedTinyException(f"Follow: alias {alias} already exists.")
        for key, value in self.directory['aliases'].items():
            if value == public_key:
                raise AlreadyUsedTinyException(f"Public key is already in contact list.")
        if bipf.encodingLength(alias) > 16:
            raise TooLongTinyException(f"Alias {alias} is too long ({bipf.encodingLength(alias)})")

        # 1.2
        self.manager.allocate_for_remote(public_key)

        # 2.0
        self.directory['aliases'][alias] = public_key

        # 3.0
        self.manager.set_in_log(self.aliases, public_key+bipf.dumps(alias))

        # Add callback
        self.manager.get_log(public_key).set_append_cb(self.manager.public_cb)

    def rename(self, old_alias, new_alias):
        """
        Rename a contact.
        Fix me: the name of the instances is not updated
        :param old_alias: the old contact name
        :param new_alias: the new contact name
        :return:
        """
        public_key = self.directory['aliases'].get(old_alias)
        if public_key is None:
            raise NotFoundTinyException(f"No contact is named {old_alias}")
        if self.directory['aliases'].get(new_alias):
            raise AlreadyUsedTinyException(f"Follow: alias {new_alias} already exists.")
        for key, value in self.directory['aliases'].items():
            if value == public_key:
                self.directory['aliases'][new_alias] = public_key
                self.directory['aliases'].pop(key)
                return # Name updated

    def unfollow(self, alias):
        """
        Unsubscribe from the feed with the given pk
        For now, we do not have a mechanism do delete a peer from current instances
        :param alias: name of the contact
        """
        # 1.3, 2.0, 3.1, _

        # 2.0
        try:
            public_key = self.directory['aliases'].pop(alias)
        except KeyError:
            raise NotFoundTinyException("Contact not deleted: not found in contact list.")

        # 3.1
        self.manager.delete_in_log(self.aliases, public_key)

    def get_contact_alias(self, public_key):
        """
        Get the human-readable alias name
        :param public_key: the public key (byte array)
        :return:
        """
        for p in self.directory['aliases'].keys():
            if self.directory['aliases'][p] == public_key:
                return p
        return None

    def resume_app(self, app_name):
        """
        Start an app that has already been created by defined_app
        :param app_name: the human-readable name of the app
        :return: instance of Application object
        """
        # _, _, _, 4.0
        if self.directory['apps'].get(app_name) is None:
            raise NotFoundTinyException(f"App {app_name} not found.")

        # 4.0
        log = self.manager.get_log(self.directory['apps'][app_name]['fid'])
        self.__current_app = application.Application(self.manager, log, self.directory['apps'][app_name]['appID'])
        return self.__current_app

    def define_app(self, app_name, appID):
        """
        Create an app-specific sub-feed (where instances will be announced)
        :param app_name: a (locally) unique name
        :param appID: a (globally) unique 32 bytes ID
        :return: instance of Application object
        """
        # 1.0, 2.0, 3.0, 4.0
        if self.directory['apps'].get(app_name) is not None:
            if self.directory['apps'][app_name]['appID'] == appID:
                return self.resume_app(app_name)
            raise AlreadyUsedTinyException(f"App {app_name} is already used")

        # If appID is already used, just change app_name
        for app in self.directory['apps']:
            if self.directory['apps'][app]['appID'] == appID:

                # 3.0
                self.manager.set_in_log(self.apps, appID+bipf.dumps(app_name))

                # 2.0
                entry = self.directory['apps'].pop(app)
                self.directory['apps'][app_name] = entry

                # 4.0
                log = self.manager.get_log(self.directory['apps'][app_name]['fid'])
                self.__current_app = application.Application(self.manager, log, appID)
                return self.__current_app

        # 1.0
        fid = self.manager.create_on_disk(self.apps, app_name, LOGTYPE_private)

        # 2.0
        self.directory['apps'][app_name] = { 'fid': fid, 'appID': appID }

        # 3.0
        self.manager.set_in_log(self.apps, appID+bipf.dumps(app_name))

        # 4.0
        self.__current_app = application.Application(self.manager, self.manager.get_log(fid), appID)

        return self.__current_app

    def delete_app(self, app_name, appID):
        """
        Delete all data (incl. logs) associated with an app
        :param app_name: a (locally) unique name
        :param appID: a (globally) unique 32 bytes ID
        """
        # 1.3, 2.0, 3.1, 4.0, 5.2
        app = self.directory['apps'].get(app_name)
        if app is None:
            raise NotFoundTinyException(f"App {app_name} does not exist (already deleted?)")
        if appID != app['appID']:
            raise TinyException(f"AppID do not match '{app_name}'")

        log = self.manager.get_log(self.directory['apps'][app_name]['fid'])
        app_inst = application.Application(self.manager, log, self.directory['apps'][app_name]['appID'])
        for inst in app_inst.instances.copy():
            app_inst.delete_inst(inst)

        # 5.2
        self.manager.write_eof(app['fid'])

        # 1.3 + 3.1
        self.manager.delete_on_disk(app['fid'], self.apps, appID + bipf.dumps(app_name))

        # 2.0
        self.directory['apps'].pop(app_name)

        # 4.0
        if self.__current_app == app_inst:
            self.__current_app = None

    def write_to_public(self, data):
        self.manager.write_in_log(self.public, data)

    def __load_contacts(self):
        """
        Read 'aliases' feed and fill the contact dictionary.
        :return: nothing
        """
        aliases_feed = self.manager.get_log(self.aliases)
        for i in range(1, len(aliases_feed)+1):
            pkt = aliases_feed[i]
            if pkt.typ[0] == packet.PKTTYPE_delete:
                fid = pkt.payload[:32]
                self.manager.deactivate_log(fid)
                to_delete = []
                for key, value in self.directory['aliases'].items():
                    if value == fid:
                        to_delete.append(key)
                for k in to_delete:
                    self.directory['aliases'].pop(k)
            if pkt.typ[0] == packet.PKTTYPE_set:
                fid = pkt.payload[:32]
                self.manager.activate_log(fid, LOGTYPE_remote)
                name = bipf.loads(pkt.payload[32:])
                assert self.directory['aliases'].get(name) is None
                self.directory['aliases'][name] = fid
                # add callback
                self.manager.get_log(fid).set_append_cb(self.manager.public_cb)

    def __load_apps(self):
        """
        Read 'apps' feed and fill the corresponding dictionary.
        """
        # 1.1, 2.0, _, _
        apps_feed = self.manager.get_log(self.apps)
        for i in range(1, len(apps_feed)+1):
            pkt = apps_feed[i]
            if pkt.typ[0] == packet.PKTTYPE_mkchild:
                fid = pkt.payload[:32]
                app_name = bipf.loads(pkt.payload[32:])
                # No checking for uniqueness: further mk_child will override feedID for an app

                # 2.0
                if self.directory['apps'].get(app_name) is None:
                    self.directory['apps'][app_name] = { 'fid': fid }
                else:
                    self.directory['apps'][app_name]['fid'] = fid

                    # 1.1
                    self.manager.deactivate_log(self.directory['apps'][app_name])
                self.manager.activate_log(fid, LOGTYPE_private)

            # only 2.0
            elif pkt.typ[0] == packet.PKTTYPE_set:
                appID = pkt.payload[:32]
                app_name = bipf.loads(pkt.payload[32:])
                # each 'set' must come after a 'mk_child'
                # (but there can be several 'set' for a 'mk_child')
                a = self.directory['apps'].get(app_name)
                if a is not None:
                    # change appID
                    a['appID'] = appID
                else:
                    # change app name
                    for a in self.directory['apps']:
                        if a.get('appID') == appID:
                            self.directory['apps'][app_name] = {'fid': a.get('fid'),
                                                                'appID': appID}
                            self.directory['apps'].pop(a)

            elif pkt.typ[0] == packet.PKTTYPE_delete:
                appID = pkt.payload[:32]
                app_name = bipf.loads(pkt.payload[32:])

                to_delete = self.directory['apps'].get(app_name)
                assert to_delete is not None
                assert to_delete['appID'] == appID
                self.manager.deactivate_log(to_delete['fid'])
                self.directory['apps'].pop(app_name)
# eof
