from types import SimpleNamespace

EMPTY = object()


class RecursiveNamespace(SimpleNamespace):
    """SimpleNamespace extension to convert nested dicts and lists."""

    @classmethod
    def from_obj(cls, obj=EMPTY, **kwargs):
        if kwargs:
            obj = kwargs
        elif obj is EMPTY:
            return cls()
        elif obj is None:
            return None
        if isinstance(obj, dict):
            return cls(**{k: cls.from_obj(v) for k, v in obj.items()})
        if isinstance(obj, list):
            return [v if isinstance(v, dict) else cls.from_obj(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(v if isinstance(v, dict) else cls.from_obj(v) for v in obj)
        return obj

    def to_dict(self):
        return {k: self.to_obj(v) for k, v in self.__dict__.items()}

    @classmethod
    def to_obj(cls, obj):
        if isinstance(obj, cls):
            return obj.to_dict()
        if isinstance(obj, list):
            return [cls.to_obj(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(cls.to_obj(v) for v in obj)
        return obj
