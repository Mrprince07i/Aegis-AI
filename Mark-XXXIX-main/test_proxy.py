import threading, time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal

class Proxy(QObject):
    sig = pyqtSignal(object)
    def __init__(self):
        super().__init__()
        self.sig.connect(self.run)
    def run(self, f):
        f()

app = QApplication([])

def worker():
    proxy = Proxy()
    proxy.moveToThread(app.thread())
    proxy.sig.emit(lambda: print('hello from main thread!'))
    time.sleep(0.5)
    proxy.sig.emit(app.quit)

threading.Thread(target=worker).start()
app.exec()
print('success')
