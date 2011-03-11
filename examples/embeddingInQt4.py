#!/usr/bin/env python
""" 
This example illustrate embedding a visvis figure in an application.
This examples uses wxPython, but the same constructions work for
pyQt or any other backend.
"""

from PyQt4 import QtGui, QtCore
import visvis as vv

# Create a visvis app instance, which wraps a qt4 application object.
# This needs to be done *before* instantiating the main window. 
app = vv.use('qt4')

class MainWindow(QtGui.QWidget):
    def __init__(self, *args):
        QtGui.QWidget.__init__(self, *args)
        
        # Make a panel with a button
        self.panel = QtGui.QWidget(self)
        but = QtGui.QPushButton(self.panel)
        but.setText('Push me')
        
        # Make figure using "self" as a parent
        self.fig = vv.backends.backend_qt4.Figure(self)
        
        # Make sizer and embed stuff
        self.sizer = QtGui.QHBoxLayout(self)
        self.sizer.addWidget(self.panel, 1)
        self.sizer.addWidget(self.fig._widget, 2)
        
        # Make callback
        but.pressed.connect(self._Plot)
        
        # Apply sizers        
        self.setLayout(self.sizer)
    
    
    def _Plot(self):
        
        # Make sure our figure is the active one. 
        # If only one figure, this is not necessary.
        #vv.figure(self.fig.nr)
        
        # Clear it
        vv.clf()
        
        # Plot
        vv.plot([1,2,3,1,6])
        vv.legend(['this is a line'])        
        #self.fig.DrawNow()
    

# Two ways to create the application and start the main loop
if True:
    # The visvis way. Will run in interactive mode when used in IEP or IPython.
    
    # Create native app
    app.Create()
    # Create window
    m = MainWindow()
    m.resize(560, 420)
    m.show()
    # Run main loop
    app.Run()

else:
    # The native way.
    
    # Create native app
    qtApp = QtGui.QApplication([''])
    # Create window
    m = MainWindow()
    m.resize(560, 420)
    m.show()
    # Run main loop
    qtApp.exec_()
