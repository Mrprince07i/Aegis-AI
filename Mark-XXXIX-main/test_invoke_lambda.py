import threading
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QMetaObject, Qt
app = QApplication([])
def worker():
    QMetaObject.invokeMethod(app, lambda: print('in lambda'), Qt.ConnectionType.QueuedConnection)
    QMetaObject.invokeMethod(app, app.quit, Qt.ConnectionType.QueuedConnection)
threading.Thread(target=worker).start()
app.exec()
print('success')
