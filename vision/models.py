"""Shared data models for the vision package."""


class Box:
    __slots__ = ("left", "top", "width", "height")

    def __init__(self, left, top, width, height):
        self.left = left
        self.top = top
        self.width = width
        self.height = height

    @property
    def cx(self):
        return self.left + self.width // 2

    @property
    def cy(self):
        return self.top + self.height // 2

    @property
    def right(self):
        return self.left + self.width

    @property
    def bottom(self):
        return self.top + self.height

    def as_dict(self):
        return {"left": self.left, "top": self.top,
                "w": self.width, "h": self.height}

    def __repr__(self):
        return (f"<Box {self.left},{self.top} {self.width}x{self.height}>")


class Word:
    __slots__ = ("box", "conf", "text")

    def __init__(self, left, top, width, height, conf, text):
        self.box = Box(left, top, width, height)
        self.conf = conf
        self.text = text

    def __repr__(self):
        return f"<Word {self.text!r} {self.box}>"


class Line:
    __slots__ = ("words", "_box")

    def __init__(self, first_word=None):
        self.words = [first_word] if first_word else []
        self._box = None

    def add(self, word):
        self.words.append(word)
        self._box = None

    @property
    def box(self):
        if self._box is None:
            left = min(w.box.left for w in self.words)
            top = min(w.box.top for w in self.words)
            right = max(w.box.right for w in self.words)
            bottom = max(w.box.bottom for w in self.words)
            self._box = Box(left, top, right - left, bottom - top)
        return self._box

    @property
    def text(self):
        return " ".join(w.text for w in sorted(self.words, key=lambda w: w.box.left))

    @property
    def conf(self):
        if not self.words:
            return 0.0
        return sum(w.conf for w in self.words) / len(self.words)

    def __repr__(self):
        return f"<Line {self.text!r} {self.box}>"
