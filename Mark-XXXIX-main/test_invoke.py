import threading
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
app = QApplication([])
def worker():
    print('in worker')
    QMetaObject.invokeMethod(app, 'quit', Qt.ConnectionType.QueuedConnection)
threading.Thread(target=worker).start()
app.exec()
print('success')
