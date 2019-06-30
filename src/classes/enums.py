from enum import Enum


class ReturnType(Enum):
	SUCCESS = 1
	INVALID_USER = 2
	USER_DOESNT_EXIST = 3
	FORBIDDEN = 4
	THREAD_LOCKED = 5
	DELETED_COMMENT = 6
