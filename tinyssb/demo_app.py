from tinyssb import util
from tinyssb.dbg import *
from tinyssb.exception import NotFoundTinyException, TinyException, NullTinyException


class DEMO:

    help = { '?': "Print this help text",
        'follow': "Follow a new peer. The public key (hex encoded) and the alias are given as argument",
        'unfollow': "Unfollow a new peer. The alias is given as argument",
        'rename': 'Rename a contact. The old and new aliases are given',
        'contact_list': "Get a list of the contacts",
        'publish': 'Write something in the public feed',
        'create_inst': 'Create an instance/game of the app. A name can optionally be given as argument',
        'add_member': 'Add a remote participant to the current instance/game. The peer name is given as argument',
        'resume_inst': 'Resume an existing instance/game of the app. The instance id must be given as argument',
        'close_inst': 'Closes an instance/game (it can be normally restarted later)',
        'replay': 'Replay all messages from an instance. Messages are ordered by feeds but not totally',
        'send': 'Send a message to an instance' }

    def __init__(self, identity, app):
        self.identity = identity
        self.app = app
        self.current_instance = '0'
        self.cmd_table = {
            '?': self.cmd_help,
            'follow': self.cmd_follow,
            'unfollow': self.cmd_unfollow,
            'rename': self.cmd_rename,
            'contact_list': self.cmd_contact_list,
            'publish': self.cmd_publish,
            'create_inst': self.cmd_create_inst,
            'add_member': self.cmd_add_member,
            'resume_inst': self.cmd_resume_inst,
            'close_inst': self.cmd_close_inst,
            'replay': self.cmd_replay,
            'send': self.cmd_send
        }

    def cmd_help(self, arg_list):
        print("TinySSB chat application")
        print("Commands are:\n")
        for c in self.cmd_table.keys():
            if c in self.help:
                print("  %-12s " % c, self.help[c])
        print("\nCommands can be abbreviated")
        print("Separate command and arguments with white spaces (\" \")\n")
        print(f"To write a message, enter the \"send\" command followed by a white space,\nthen write your text")

    def cmd_follow(self, arg_list):
        if len(arg_list) != 2:
            dbg(YEL, f"\"Follow\" needs 2 arguments (public key and alias), {len(arg_list)} were given")
            return
        try:
            public_key = util.fromhex(arg_list[0])
        except ValueError as e:
            dbg(YEL, f"Value error: {e}")
            return

        self.identity.follow(public_key, arg_list[1])
        dbg(GRE, f"{arg_list[1]} added to your contacts")

    def cmd_rename(self, arg_list):
        if len(arg_list) != 2:
            dbg(YEL, f"\"Rename\" needs 2 arguments (old alias and new alias), {len(arg_list)} were given")
            return
        try:
            self.identity.rename(arg_list[0], arg_list[1])
        except ValueError as e:
            dbg(YEL, f"Value error: {e}")
            return

        dbg(GRE, f"{arg_list[0]} renamed to {arg_list[1]}")

    def cmd_unfollow(self, arg_list):
        if len(arg_list) != 1:
            dbg(YEL, f"\"Unfollow\" needs 1 argument (alias), {len(arg_list)} were given")
            return

        self.identity.unfollow(arg_list[0]),

        dbg(GRE, f"{arg_list[0]} removed from your contacts")

    def cmd_contact_list(self, arg_list):
        dbg(GRE, f"{self.identity.directory['aliases'].keys()}")

    def cmd_publish(self, arg_list):
        if len(arg_list) != 1:
            dbg(YEL, f"\"Publish\" needs 1 argument, {len(arg_list)} were given")
            return

        self.identity.write_to_public(arg_list[0]),

    def cmd_create_inst(self, arg_list):
        try:
            self.current_instance = self.app.create_inst(arg_list)
        except TinyException as e:
            dbg(YEL, f"Error: {e}")
        dbg(GRE, f"New instance created with id = {self.current_instance}")

    def cmd_add_member(self, arg_list):
        if len(arg_list) != 2:
            dbg(YEL, f"\"Add remote\" needs 2 arguments (remote feed ID and alias), {len(arg_list)} were given")
            return
        try:
            remote_fid = util.fromhex(arg_list[0])
            with_ = self.identity.directory['aliases'][arg_list[1]]
        except KeyError:
            dbg(YEL, f"Key error: there is no contact named \"{arg_list[1]}\"")
            return
        try:
            self.app.add_member(self.current_instance, remote_fid, with_)
            dbg(GRE, f"{arg_list[1]} added to the chat \"{self.current_instance}\"")

        except NotFoundTinyException as e:
            dbg(YEL, f"NotFoundTinyException: {e}. (Should you create one?)")
        except ValueError as e:
            dbg(YEL, f"Value error: {e}")

    def cmd_resume_inst(self, arg_list):
        if len(arg_list) != 1:
            dbg(YEL, f"\"Resume instance\" needs 1 argument (instance id), {len(arg_list)} were given")
            return
        try:
            self.app.resume_inst(arg_list[0])
            self.current_instance = arg_list[0]
        except NotFoundTinyException:
            dbg(YEL, f"Instance {arg_list[0]} was not found. Valid ids are:\n{self.app.instances.keys()}")

    def cmd_close_inst(self, arg_list):
        try:
            self.app.close_inst(self.current_instance)
            self.current_instance = None
        except NotFoundTinyException:
            dbg(YEL, f"No instance was closed")

    def cmd_replay(self, arg_list):
        try:
            self.app.replay()
        except NullTinyException as e:
            dbg(YEL, f"{e}")

    def cmd_send(self, arg_list):
        if self.current_instance is None:
            dbg(YEL, f"No instance is running. Create or resume a chat before sending a message.")
            return
        self.app.send(' '.join(arg_list))
        dbg(MAG, f"I sent \"{' '.join(arg_list)}\"")

    def cmd_exit(self, arg_list):
        self.cmd_close_inst("")
        print(f"\nExiting: {arg_list}")
        sys.exit(0)

    def demo_loop(self, name):
        if name == 'Alice':
            self.cmd_follow(['6a7599019df4b5bf09781b6a3653946c278a5cdc236ea60d917ede9ee3cf314d', 'Ed'])
            self.cmd_follow(['48b3d5930f8ea1300a3ad33a8220a0dc7943e671e88946b11cc2b206a4812582', 'Fred'])
        cmd = ""
        dbg(GRE, f"Welcome to tiny chat. Send \"?\" to see the different commands options.")
        while True:
            try:
                cmd = input(f">> ")
            except (EOFError, KeyboardInterrupt) as e:
                self.cmd_exit(e)
            cmd = cmd.split(" ")
            lst = [c for c in self.help if c.startswith(cmd[0])]  # find corr. command ("startswith" is enough)

            if len(cmd) == 1 and cmd[0] == '':
                print("Empty command, new loop iteration")
                continue
            elif not lst:
                print("unknown command. Use ? to see list of commands")
                continue
            elif len(lst) > 1:  # more than one comm. match
                print("ambiguous command. Use ? to see list of commands")
                continue

            try:
                self.cmd_table[lst[0]](cmd[1:])
            except TypeError as e:
                dbg(YEL, f"Error: {e}")

            try:
                inst_name = ""
                if self.app.instances[self.current_instance]['n']:
                    inst_name = f" ({self.app.instances[self.current_instance]['n']})"
                dbg(GRA, f"Current instance is {self.current_instance}{inst_name}.")
            except KeyError:
                dbg(YEL, f"No instance is currently running")
# eof
