from PyQt6.QtCore import QTimer, QApplication
app = QApplication.instance()
print(hasattr(QTimer, 'singleShot'))
