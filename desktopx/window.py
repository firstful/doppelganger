"""Window model + discovery."""


class Window:
    def __init__(self, driver, win_id, title="", cls=""):
        self.driver = driver
        self.id = win_id
        self.title = title
        self.cls = cls

    def __repr__(self):
        return f"<Window id={self.id} title={self.title!r} cls={self.cls!r}>"

    def activate(self):
        return self.driver.activate(self.id)

    def raise_(self):
        return self.driver.raise_(self.id)

    def geometry(self):
        return self.driver.geometry(self.id)

    def move_resize(self, x=None, y=None, w=None, h=None):
        return self.driver.move_resize(self.id, x=x, y=y, w=w, h=h)

    def screenshot(self, path=None):
        return self.driver.screenshot(self.id, path)


def discover_windows(driver):
    return driver.list_windows()