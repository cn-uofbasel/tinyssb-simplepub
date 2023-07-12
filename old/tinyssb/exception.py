# tinyssb/exception.py
# 2022-05-25 <et.mettaz@unibas.ch>

class TinyException(Exception):
    def __init__(self, value):
        self.value = value

class AlreadyUsedTinyException(TinyException):
    def __init__(self, value):
        self.value = value

class TooLongTinyException(TinyException):
    def __init__(self, value):
        self.value = value

class NotFoundTinyException(TinyException):
    def __init__(self, value):
        self.value = value

class NullTinyException(TinyException):
    def __init__(self, value):
        self.value = value

class UnexpectedPacketTinyException(TinyException):
    def __init__(self, value):
        self.value = value

if __name__ == "__main__":
    try:
        raise AlreadyUsedTinyException("Test")
    except TinyException as e:
        print(f"Err: {e}")
