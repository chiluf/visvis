#   This file is part of VISVIS.
#    
#   VISVIS is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Lesser General Public License as 
#   published by the Free Software Foundation, either version 3 of 
#   the License, or (at your option) any later version.
# 
#   VISVIS is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU Lesser General Public License for more details.
# 
#   You should have received a copy of the GNU Lesser General Public 
#   License along with this program.  If not, see 
#   <http://www.gnu.org/licenses/>.
#
#   Copyright (C) 2009 Almar Klein

""" Module textures

Defined the texture base class and the Texture2D and Texture3D
wobjects. 

2D textures can be visualized without using GLSL. If GLSL is enabled, it
allows using clim, colormap and antialiasing (aa property).

3D textures are rendered using GLSL shader programs. The shader can be
selected using texture3D.renderStyle = 'ray', where 'ray' can be the
name of any of the available fragment shaders.

$Author$
$Date$
$Rev$

"""

import OpenGL.GL as gl
import OpenGL.GL.ARB.shader_objects as gla
import OpenGL.GLU as glu

import numpy as np
import math, time, os

from misc import getResourceDir
from misc import Property, Range, OpenGLError, Position
from events import *
from base import Wobject, getGlVersion
from misc import Transform_Translate, Transform_Scale, Transform_Rotate

import points


dtypes = {  'uint8':gl.GL_UNSIGNED_BYTE,    'int8':gl.GL_BYTE,
            'uint16':gl.GL_UNSIGNED_SHORT,  'int16':gl.GL_SHORT, 
            'uint32':gl.GL_UNSIGNED_INT,    'int32':gl.GL_INT, 
            'float32':gl.GL_FLOAT }

# A correction for the clim. For a datatype of uint8, the fragents
# are mapped between 0 and 1 for 0 and 255 respectively. For int8
# the values are mapped between -1 and 1 for -127 and 128 respectively.
climCorrection = { 'uint8':2**8, 'int8':2**7, 'uint16':2**16, 'int16':2**15, 
                   'uint32':2**32, 'int32':2**31, 'float32':1, 'float64':1,
                   'bool':2**8}


def loadShaders():
    """ load shading code from the files in the resource dir.
    Returns two dicts with the vertex and fragment shaders, 
    respectively. """
    path = getResourceDir()
    vshaders = {}
    fshaders = {}
    for filename in os.listdir(path):
        
        # only glsl files
        if not filename.endswith('.glsl'):
            continue
        
        # read code
        f = open( os.path.join(path, filename) )
        tekst = f.read()
        f.close()
        
        # insert into this namespace
        if filename.endswith('.vertex.glsl'):
            varname = filename[:-12].lower()
            vshaders[varname] = tekst
        elif filename.endswith('.fragment.glsl'):
            varname = filename[:-14].lower()
            fshaders[varname] = tekst
    
    return vshaders, fshaders

# load shaders
vshaders, fshaders = loadShaders()



class GlslProgram:
    """ GLSL program
    A class representing a GLSL (OpenGL Shading Language) program.
    It provides an easy interface for adding vertex and fragment shaders
    and setting variables used in them.
    Note: On systems that do not support shading, this class will go in
    invalid mode.
    """
    
    _toldAboutVersion = False
    
    def __init__(self):
        # ids
        self._programId = 0
        self._shaderIds = []
        
        # code for the shaders        
        self._fragmentCode = ''
        self._vertexCode = ''
        
        # is usable?
        self._usable = True
        # can use shaders or not?
        if getGlVersion() >= '2.0': # todo: is this 2.0 or 2.1?
            pass
        else:
            if not GlslProgram._toldAboutVersion:
                tmp = "the version of OpenGL on this system does not support GLSL."
                tmp += " Therefore anti-aliasing, the clim property, colormaps,"
                tmp += " and 3D rendering are disabled."
                print "Warning: "+tmp
                GlslProgram._toldAboutVersion = True
            self._usable = False
    
    def IsUsable(self):
        """ Returns whether the program is usable. """ 
        return self._usable
    
    def _IsCompiled(self):
        if not self._usable:
            return False
        else:
            return ( self._programId>0 and gl.glIsProgram(self._programId) )
    
    
    def Enable(self):
        """ Start using the program. """
        if not self._usable:
            return
        
        if (self._fragmentCode or self._vertexCode) and not self._IsCompiled():
            self._CreateProgramAndShaders()
        
        if self._IsCompiled():
            gla.glUseProgramObjectARB(self._programId)
            self._checkForOpenglError('Use')
        else:
            gla.glUseProgramObjectARB(0)
    
    
    def Disable(self):
        """ Stop using the program. """
        if not self._usable:
            return
        gla.glUseProgramObjectARB(0)
    
    
    def SetVertexShader(self, code):
        """ Create a vertex shader from code and attach to the program.
        """
        self._vertexCode = code
        self.DestroyGl()


    def SetFragmentShader(self, code):
        """ Create a fragment shader from code and attach to the program.
        """
        self._fragmentCode = code
        self.DestroyGl()
    
    
    def SetVertexShaderFromFile(self, path):
        try:
            f = open(path, 'r')
            code = f.rad()
            f.close()
        except Exception, why:
            print "Could not create shader: ", why            
        self.SetVertexShader(code)
    
    
    def SetFagmentShaderFromFile(self, path):
        try:
            f = open(path, 'r')
            code = f.read()
            f.close()            
        except Exception, why:
            print "Could not create shader: ", why            
        self.SetFragmentShader(code)
   
    
    def _CreateProgramAndShaders(self):
        # clear any old programs and shaders
        
        if self._programId < 0:
            return
        
        # clear to be sure
        self.DestroyGl()
        
        if not self._fragmentCode and not self._vertexCode:
            self._programId = -1  # don't make a shader object
            return
        
        try:
            # create program object
            self._programId = gla.glCreateProgramObjectARB()
            self._checkForOpenglError('CreateProgram')
            
            # the two shaders
            codes = [self._fragmentCode, self._vertexCode]
            types = [gl.GL_FRAGMENT_SHADER, gl.GL_VERTEX_SHADER]
            for code, type in zip(codes, types):
                # only attach shaders that do something
                if not code:
                    continue
                
                # create shader object            
                myshader = gla.glCreateShaderObjectARB(type)            
                self._checkForOpenglError('CreateShader')
                self._shaderIds.append(myshader)
                
                # set its source            
                gla.glShaderSourceARB(myshader, [code])
                self._checkForOpenglError('ShaderSource')
                
                # compile shading code
                gla.glCompileShaderARB(myshader)
                self._checkForOpenglError('CompileShader')
                
                # errors?
                if not self._ProcessErrors(myshader):
                    gla.glAttachObjectARB(self._programId, myshader)
                    self._checkForOpenglError('AttachShader')
            
            # link shader
            gla.glLinkProgramARB(self._programId)
            self._checkForOpenglError('Link')
            
        except Exception, why:
            self._programId = -1
            print "Unable to initialize shader code.", why
    
    
    def SetUniformf(self, varname, values):
        """ A uniform is a parameter for shading code.
        Set the parameters right after enabling the program.
        values should be a list of up to four floats ( which 
        are converted to float32).
        """
        if not self._IsCompiled():
            return
        
        # convert to floats
        values = [float(v) for v in values]
        
        # get loc
        loc = gla.glGetUniformLocationARB(self._programId, varname)        
        
        # set values
        if len(values) == 1:
            gl.glUniform1f(loc, values[0])
        elif len(values) == 2:
            gl.glUniform2f(loc, values[0], values[1])            
        elif len(values) == 3:
            gl.glUniform3f(loc, values[0], values[1], values[2])
        elif len(values) == 4:
            gl.glUniform4f(loc, values[0], values[1], values[2], values[3])
    
    
    def SetUniformi(self, varname, values):
        """ A uniform is a parameter for shading code.
        Set the parameters right after enabling the program.
        values should be a list of up to four ints ( which 
        are converted to int).
        """
        if not self._IsCompiled():
            return
        
        # convert to floats
        values = [int(v) for v in values]
        
        # get loc
        loc = gla.glGetUniformLocationARB(self._programId, varname)        
        
        # set values
        if len(values) == 1:
            gla.glUniform1iARB(loc, values[0])
        elif len(values) == 2:
            gl.glUniform2iARB(loc, values[0], values[1])            
        elif len(values) == 3:
            gl.glUniform3iARB(loc, values[0], values[1], values[2])
        elif len(values) == 4:
            gl.glUniform4iARB(loc, values[0], values[1], values[2], values[3])
    
    
    def _checkForOpenglError(self, s):
        e = gl.glGetError()
        if (e != gl.GL_NO_ERROR):
            raise OpenGLError('GLERROR: ' + s + ' ' + glu.gluErrorString(e))
    
    
    def _ProcessErrors(self, glObject):
        log = gla.glGetInfoLogARB(glObject)
        if log:
            print "Warning in shading code:", log
            return True
        else:
            return False
    
    
    def DestroyGl(self):
        """ Clear the program. """
        # clear OpenGL stuff
        if not self._usable:
            return
        if self._programId>0:
            try: gla.glDeleteObjectARB(self._programId)
            except Exception: pass
        for shaderId in self._shaderIds:
            try:  gla.glDeleteObjectARB(shaderId)
            except Exception: pass
        # reset
        self._programId = 0
        self._shaderIds[:] = []
    
    
    def __del__(self):
        " You never know when this is called."
        self.DestroyGl()


def downSample(data, ndim):
    """ Downsample the data. Peforming a simple form of smoothing to prevent
    aliasing. """
    if ndim==1:
        data2 = 0.4 * data
        data2[1:] += 0.3*data[:-1] 
        data2[:-1] += 0.3*data[1:]
        data2 = data2[::2]
    elif ndim==2:
        data2 = 0.4 * data        
        data2[1:,:] += 0.15*data[:-1,:] 
        data2[:-1,:] += 0.15*data[1:,:]
        data2[:,1:] += 0.15*data[:,:-1] 
        data2[:,:-1] += 0.15*data[:,1:,:]
        data2 = data2[::2,::2]
    elif ndim==3:
        data2 = 0.4 * data        
        data2[1:,:,:] += 0.1*data[:-1,:,:] 
        data2[:-1,:,:] += 0.1*data[1:,:,:]
        data2[:,1:,:] += 0.1*data[:,:-1,:] 
        data2[:,:-1,:] += 0.1*data[:,1:,:]
        data2[:,:,1:] += 0.1*data[:,:,:-1] 
        data2[:,:,:-1] += 0.1*data[:,:,1:]        
        data2 = data2[::2,::2,::2]
    else:
        raise ValueError("Cannot downsample data of this dimension.")
    return data2



class TextureObject(object):
    """ TextureObject(texType)
    
    Basic texture class that wraps an OpenGl texture. It manages the OpenGl
    class and exposes a rather high-level interface to it.
    
    texType is one of gl.GL_TEXTURE_1D, gl.GL_TEXTURE_2D, gl.GL_TEXTURE_3D
    and specifies whether this is a 1D, 2D or 3D texture.
    
    Exposed methods:
    - Enable() call be for using
    - Disable() call after using
    - SetData() update the data    
    - DestroyGl() remove only the texture from OpenGl memory.
    - Destroy() remove textures and reference to data.
    Note: this is not a Wobject nor Wibject.
    """
    
    # One could argue to use polymorphism to implement 3 classes: one for 
    # each dimension. Yes you could, but the way to handle the data and
    # communicate with OpenGl is so similar I chose not to. I use the
    # texType to determine which function to call. 
    
    def __init__(self, texType):
        
        # Check given texture type
        tmp = [gl.GL_TEXTURE_1D, gl.GL_TEXTURE_2D, gl.GL_TEXTURE_3D]
        if texType not in tmp:
            raise ValueError("texType should be one of gl.GL_TEXTURE_*D.")
        
        # Store the texture type. This attribute is used to make the 
        # choices for which OpenGl functions to use etc.
        self._texType = texType
        
        # Texture ID. This is an integer by which OpenGl identifies the 
        # texture.
        self._texId = 0
        
        # To store the used texture unit so we can disable it properly.
        self._texUnit = -1
        
        # The shape of the data as uploaded to OpenGl. Is None if no
        # data was uploaded. Note that the self._shape does not have to 
        # be self._dataRef.shape; the data might be downsampled.
        self._shape = None
        
        # A reference (not a weak one) to the original data as given with 
        # SetData. We need this in order to re-upload the texture if it is 
        # moved to another OpenGl context (other figure).
        # Note that the self._shape does not have to be self._dataRef.shape.
        self._dataRef = None
        
        # A flag to indicate that the data in self._dataRef should be uploaded.
        # 0 signifies no upload required. 1 signifies an update is required.
        # -1 signifies the current data failed to upload last time.
        self._uploadFlag = 0
    
    
    def Enable(self, texUnit=0):
        """ Enable(texUnit)
        Enable (bind) the texture, using the given texture unit (max 9).
        If necessary, will upload/update the texture in OpenGl memory now.
        """ 
        
        # did last time go alright?
        troubleLastTime = (self._uploadFlag == -1)
        
        # If texture invalid, tell to upload
        if self._texId == 0 or not gl.glIsTexture(self._texId):            
            if not troubleLastTime: # prevent keep trying to update
                self._uploadFlag = 1
        
        # If we should upload/update, do that now. (SetData also sets the flag)
        if self._uploadFlag==1:
            self._SetDataNow()
        
        # check if ok now
        if not gl.glIsTexture(self._texId):
            if not troubleLastTime:
                tmp = " (Hiding message for future draws.)"
                print "Warning enabling texture, the texture is not valid."+tmp
            return
        
        # Store texture-Unit-id, and activate 
        self._texUnit = texUnit
        gl.glActiveTexture( gl.GL_TEXTURE0 + texUnit )   # Opengl v1.3 
        
        # Enable texturing, and bind to texture
        gl.glEnable(self._texType)
        gl.glBindTexture(self._texType, self._texId)
    
    
    def Disable(self):
        """ Disable()
        Disable the texture. It's safe to call this, even if the texture
        was not enabled.
        """
        
        # Select active texture if we can
        if self._texUnit >= 0:
            gl.glActiveTexture( gl.GL_TEXTURE0 + self._texUnit )            
            self._texUnit = -1
        
        # Disable
        gl.glDisable(self._texType)
        
        # Set active texture unit to default (0)
        gl.glActiveTexture( gl.GL_TEXTURE0 )
    
   
    def SetData(self, data):
        """ SetData(data)
        Set the data to display. If possible, will update the data in the
        existing texture (is possible if of the same shape).
        """
        
        # check data
        if not isinstance(data, np.ndarray):
            raise ValueError("Data should be a numpy array.")
        
        # check shape (raises ValueError if not ok)
        try:
            self._GetFormat(data.shape)
        except ValueError:
            raise # reraise from here
        
        # ok, store data and raise flag
        self._dataRef = data
        self._uploadFlag = 1
    
    
    def _SetDataNow(self):
        """ Make sure the data in self._dataRef is uploaded to 
        OpenGl memory. If possible, update the data rather than 
        create a new texture object.
        """
        
        # set flag to failes (set to success at the end)
        self._uploadFlag = -1
        
        # Get data. 
        if self._dataRef is None:
            return
        data = self._dataRef
        
        # Make singles if doubles (sadly opengl does not know about doubles)
        if data.dtype == np.float64:
            data = data.astype(np.float32)
        # dito for bools
        if data.dtype == np.bool:
            data = data.astype(np.uint8)
        
        # Determine type
        thetype = data.dtype.name
        if not thetype in dtypes:
            # this should not happen, since we concert incompatible types
            raise ValueError("Cannot convert datatype %s." % thetype)
        gltype = dtypes[thetype]
        
        # Determine format
        internalformat, format = self._GetFormat(data.shape)
        
        # determine dimensions
        D = {gl.GL_TEXTURE_1D:1, gl.GL_TEXTURE_2D:2, gl.GL_TEXTURE_3D:3}
        ndim = D[self._texType]
        
        # Can we update or should we upload?        
        
        if (    gl.glIsTexture(self._texId) and 
                self._shape and (data.shape == self._shape) ):
            # We can update.
            
            # Bind to texture
            gl.glBindTexture(self._texType, self._texId)
            
            # update            
            self._UpdateTexture(data, ndim, internalformat, format, gltype)
        
        else:
            # We should upload.
            
            # Remove any old data. 
            self.DestroyGl()
            
            # Create texture object
            self._texId = gl.glGenTextures(1)
            
            # Bind to texture
            gl.glBindTexture(self._texType, self._texId)
            
            # test whether it fits, downsample if necessary
            ok, count = False, 0
            while not ok and count<8:
                ok = self._TestUpload(data,ndim, internalformat,format,gltype)
                if not ok:
                    data = downSample(data, ndim)
                    count += 1
            
            # give warning or error
            if count and not ok:                
                raise MemoryError(  "Could not upload texture to OpenGL, " +
                                    "even after 8 times downsampling.")
            elif count:
                print(  "Warning: data was downscaled " + str(count) + 
                        " times to fit it in OpenGL memory." )
            
            # upload!
            self._UploadTexture(data, ndim, internalformat, format, gltype)
            
            # keep reference of data shape (as loaded to opengl)
            self._shape = data.shape
        
        
        # flag success
        self._uploadFlag = 0
    
    
    
    def _UpdateTexture(self, data, ndim, internalformat, format, gltype):
        """ Update an existing texture object. It should have been 
        checked whether this is possible (same shape).
        """
        
        # define dict
        D = {   1: (gl.glTexSubImage1D, gl.GL_TEXTURE_1D),
                2: (gl.glTexSubImage2D, gl.GL_TEXTURE_2D),
                3: (gl.glTexSubImage3D, gl.GL_TEXTURE_3D)}
        
        # determine function and target from texType
        uploadFun, target = D[ndim]
        
        # Build argument list
        shape = [i for i in reversed( list(data.shape[:ndim]) )]
        args = [target, 0] + [0 for i in shape] + shape + [format,gltype,data]
        
        # Upload!
        uploadFun(*tuple(args))
    
    
    def _TestUpload(self, data, ndim, internalformat, format, gltype):
        """ Test whether we can create a texture of the given shape.
        Returns True if we can, False if we can't.
        """
        
        # define dict
        D = {   1: (gl.glTexImage1D, gl.GL_PROXY_TEXTURE_1D),
                2: (gl.glTexImage2D, gl.GL_PROXY_TEXTURE_2D),
                3: (gl.glTexImage3D, gl.GL_PROXY_TEXTURE_3D)}
        
        # determine function and target from texType
        uploadFun, target = D[ndim]
        
        # build args list
        shape = [i for i in reversed( list(data.shape[:ndim]) )]
        args = [target, 0, internalformat] + shape + [0, format, gltype, None]
        
        # do fake upload
        uploadFun(*tuple(args))
        
        # test and return
        ok = gl.glGetTexLevelParameteriv(target, 0, gl.GL_TEXTURE_WIDTH)
        return bool(ok)
    
    
    def _UploadTexture(self, data, ndim, internalformat, format, gltype):
        """ Upload a texture to the current texture object. 
        It should have been verified that the texture will fit.
        """
        
        # define dict
        D = {   1: (gl.glTexImage1D, gl.GL_TEXTURE_1D),
                2: (gl.glTexImage2D, gl.GL_TEXTURE_2D),
                3: (gl.glTexImage3D, gl.GL_TEXTURE_3D)}
        
        # determine function and target from texType
        uploadFun, target = D[ndim]
        
        # build args list
        shape = [i for i in reversed( list(data.shape[:ndim]) )]
        args = [target, 0, internalformat] + shape + [0, format, gltype, data]
        
        # call
        uploadFun(*tuple(args))
    
    
    def _GetFormat(self, shape):
        """ Get internalformat and format, based on the self._texType
        and the shape. If the shape does not match with the texture
        type, an exception is raised.
        """
        
        if self._texType == gl.GL_TEXTURE_1D:
            if len(shape)==1:
                iformat, format = gl.GL_LUMINANCE8, gl.GL_LUMINANCE
            elif len(shape)==2 and shape[1] == 1:
                iformat, format = gl.GL_LUMINANCE8, gl.GL_LUMINANCE
            elif len(shape)==2 and shape[1] == 3:
                iformat, format = gl.GL_RGB, gl.GL_RGB
            elif len(shape)==2 and shape[1] == 4:
                iformat, format = gl.GL_RGBA, gl.GL_RGBA
            else:
                raise ValueError("Cannot create 1D texture, data of invalid shape.")
        
        elif self._texType == gl.GL_TEXTURE_2D:
        
            if len(shape)==2:
                iformat, format = gl.GL_LUMINANCE8, gl.GL_LUMINANCE                
            elif len(shape)==3 and shape[2]==1:
                iformat, format = gl.GL_LUMINANCE8, gl.GL_LUMINANCE
            elif len(shape)==3 and shape[2]==3:
                iformat, format = gl.GL_RGB, gl.GL_RGB
            elif len(shape)==3 and shape[2]==4:
                iformat, format = gl.GL_RGBA, gl.GL_RGBA
            else:
                raise ValueError("Cannot create 2D texture, data of invalid shape.")
        
        elif self._texType == gl.GL_TEXTURE_3D:
        
            if len(shape)==3:
                iformat, format = gl.GL_LUMINANCE8, gl.GL_LUMINANCE
            elif len(shape)==4 and shape[3]==1:
                iformat, format = gl.GL_LUMINANCE8, gl.GL_LUMINANCE
            elif len(shape)==4 and shape[3]==3:
                iformat, format = gl.GL_RGB, gl.GL_RGB
            elif len(shape)==4 and shape[3]==4:
                iformat, format = gl.GL_RGBA, gl.GL_RGBA
            else:
                raise ValueError("Cannot create 3D texture, data of invalid shape.")
        
        return iformat, format
    
    
    def DestroyGl(self):
        """ DestroyGl()
        Removes the texture from OpenGl memory. The internal reference
        to the original data is kept though.
        """
        try:
            if self._texId > 0:
                gl.glDeleteTextures([self._texId])
        except Exception:
            pass
        self._texId = 0
    
    
    def Destroy(self):
        """ Destroy()
        Really destroy data. 
        """  
        # remove OpenGl bits      
        self.DestroyGl()
        # remove internal reference
        self._dataRef = None
        self._shape = None
    
    
    def __del__(self):
        self.Destroy()


class Colormap(TextureObject):
    """ Colormap()
    A colormap represents a table of colours to map
    grayscale data.
    """
    
    # Note that the OpenGL imaging subset also implements a colormap,
    # but it is not guaranteed that the subset is available.
    
    def __init__(self):
        TextureObject.__init__(self, gl.GL_TEXTURE_1D)
        
        # CT: (0,0,0,0.0), (1,0,0,0.002), (0,0.5,1,0.6), (0,1,0,1)                
        self._current = [(0,0,0), (1,1,1)]
        self.SetMap(self._current)
    
    
    def _UploadTexture(self, data, *args):
        """ Overloaded version to upload the texture. """
        
        # let the original class do the work
        TextureObject._UploadTexture(self, data, *args)
        
        # set interpolation and extrapolation parameters            
        tmp = gl.GL_NEAREST # gl.GL_NEAREST | gl.GL_LINEAR
        gl.glTexParameteri(gl.GL_TEXTURE_1D, gl.GL_TEXTURE_MIN_FILTER, tmp)
        gl.glTexParameteri(gl.GL_TEXTURE_1D, gl.GL_TEXTURE_MAG_FILTER, tmp)
        gl.glTexParameteri(gl.GL_TEXTURE_1D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP)
    
    
    def GetMap(self):
        """ GetMap()
        Get the current texture map, as last set with SetMap().
        """
        return self._current
    
    
    def GetData(self):
        """ GetData()
        Get the full colormap as a 256x4 numpy array.
        """
        return self._dataRef
    
    
    def SetMap(self, *args):
        """ SetMap(self, (r,g,b), (r,g,b), (r,g,b)), or
        SetMap(self, [(r,g,b), (r,g,b), (r,g,b)])
        Set the colormap data. 
        For now, only accepts lists of lists (or tuples).
        """
        
        # one argument given?
        if len(args)==1:
            args = args[0]
        
        # store
        self._current = args
        
        # init
        data = None
        
        # parse input
        if isinstance(args, (tuple, list)):
            data = np.zeros((len(args),4), dtype=np.float32)
            data[:,3] = 1.0 # init alpha to be all ones
            count = -1
            for el in args:
                count += 1
                if not hasattr(el,'__len__') or len(el) not in [3,4]:
                    raise ValueError('Colormap entries must have 3 or 4 elements.')
                elif len(el)==3:
                    data[count,0] = el[0]
                    data[count,1] = el[1]
                    data[count,2] = el[2]
                elif len(el)==4:
                    data[count,0] = el[0]
                    data[count,1] = el[1]
                    data[count,2] = el[2]
                    data[count,3] = el[3]
        elif isinstance(args, np.ndarray):
            if args.ndim != 2 or args.shape[1] not in [3,4]:
                raise ValueError('Colormap entries must have 3 or 4 elements.')
            elif args.shape[1]==3:
                data = np.zeros((args.shape[0],4), dtype=np.float32)
                data[:,3] = 1.0
                for i in range(3):
                    data[:,i] = args[i]
            elif args.shape[1]==4:
                data = args
            else:
                raise ValueError("Invalid argument to set colormap.")
        
        # apply
        if data is not None:   
            if data.shape[0] == 256 and data.dtype == np.float32:
                data2 = data
            else:
                # interpolate first            
                x = np.linspace(0.0, 1.0, 256)
                xp = np.linspace(0.0, 1.0, data.shape[0])            
                data2 = np.zeros((256,4),np.float32)
                for i in range(4):
                    data2[:,i] = np.interp(x, xp, data[:,i])
            # store texture
            #self._data = data2
            self.SetData(data2)


class TextureObjectToVisualize(TextureObject):
    """ A texture object aimed more towards visualization. 
    This is what is actually used in Texture2D and Texture3D objects.
    It has no propererties, but some private attributes
    which are set by the real interface (the Texture*D objects).
    Basically, it handles the color limits.
    """
    
    def __init__(self, texType, data):
        TextureObject.__init__(self, texType)
        
        # interpolate?
        self._interpolate = False
        
        # the limits
        self._clim = Range(0,1)
        self._climCorrection = 1.0
        self._climRef = Range(0,1) # the "original" range
        
        # init clim and colormap
        self._climRef.Set(data.min(), data.max())
        self._clim = self._climRef.Copy()
    
    
    def _UploadTexture(self, data, ndim, *args):
        """ "Overloaded" method to upload texture data
        """
        
        # Set alignment to 1. It is 4 by default, but my data array has no
        # strides, so in order for the image not to be distorted, I set it 
        # to 1. I assume graphics cards can still render in hardware. If 
        # not, I would have to add one or two rows to my data instead.
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT,1)
        
        # init transferfunctions and set clim to full range
        self._ScaleBias_init(data.dtype.name)
        
        # create texture
        TextureObject._UploadTexture(self, data, ndim, *args)
        
        # set interpolation and extrapolation parameters            
        tmp1 = gl.GL_NEAREST
        tmp2 = {False:gl.GL_NEAREST, True:gl.GL_LINEAR}[self._interpolate]
        gl.glTexParameteri(self._texType, gl.GL_TEXTURE_MIN_FILTER, tmp1)
        gl.glTexParameteri(self._texType, gl.GL_TEXTURE_MAG_FILTER, tmp2)
        gl.glTexParameteri(self._texType, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP)
        gl.glTexParameteri(self._texType, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP)
        
        # reset transfer
        self._ScaleBias_afterUpload()
        
        # should we correct for downsampling?
        factor = self._dataRef.shape[0] / float(data.shape[0])
        if factor > 1:
            self._trafo_scale.sx *= factor 
            self._trafo_scale.sy *= factor
            if ndim==3:
                self._trafo_scale.sz *= factor
        
        # Set clamping. When testing the raycasting, comment these lines!
        if ndim==3:
            gl.glTexParameteri(self._texType, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP)
            gl.glTexParameteri(self._texType, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP)
            gl.glTexParameteri(self._texType, gl.GL_TEXTURE_WRAP_R, gl.GL_CLAMP)
    
    
    def _OnUpdate(self, data, *args):
        """ "Overloaded" method to update texture data
        """
        
        # init transferfunctions and set clim to full range
        self._ScaleBias_init(data.dtype.name)
        
        # create texture
        self._texture1._UpdateTexture(data, *args)
        
        # reset transfer
        self._ScaleBias_afterUpload()
    
    
    def _ScaleBias_init(self, datatype):
        """ Given the climRef (which is set to data.min() and data.max())
        in constructor, set the scale 
        and bias for copying data to opengl memory. Correct for the dataype.
        Also set the default value for clim to the full data range.
        
        More info: OpenGL will map the full range of the datatype
        to 0:1 for unsigned datatypes, and to -1:1 for signed datatypes.
        For floats, 0:1 is mapped to 0:1. We modify the scale, such that
        the full range of the data (not the datatype) is scaled between 0:1.
        This way we can also visualize float data with values other than 0:1.
        """
        # store data range as a reference and init clim with that
        #self._clim = self._climRef.Copy()
        # calculate scale and bias
        ran = self._climRef.range
        if ran==0:
            ran = 1.0
        scale = climCorrection[datatype] / ran
        bias = -self._climRef.min / ran
        # set transfer functions
        gl.glPixelTransferf(gl.GL_RED_SCALE, scale)
        gl.glPixelTransferf(gl.GL_GREEN_SCALE, scale)
        gl.glPixelTransferf(gl.GL_BLUE_SCALE, scale)
        gl.glPixelTransferf(gl.GL_RED_BIAS, bias)
        gl.glPixelTransferf(gl.GL_GREEN_BIAS, bias)
        gl.glPixelTransferf(gl.GL_BLUE_BIAS, bias)
    
    
    def _ScaleBias_afterUpload(self):
        """ Reset the transferfunctions. """
        gl.glPixelTransferf(gl.GL_RED_SCALE, 1.0)
        gl.glPixelTransferf(gl.GL_GREEN_SCALE, 1.0)
        gl.glPixelTransferf(gl.GL_BLUE_SCALE, 1.0)
        gl.glPixelTransferf(gl.GL_RED_BIAS, 0.0)
        gl.glPixelTransferf(gl.GL_GREEN_BIAS, 0.0)
        gl.glPixelTransferf(gl.GL_BLUE_BIAS, 0.0)
    
    
    def _ScaleBias_get(self):
        """ Given clim, get scale and bias to apply in shader."""
        # ger ranges and correct if zero
        r1, r2 = self._clim.range, self._climRef.range
        if r1==0:
            r1 = 1.0
        if r2==0:
            r2 = 1.0
        # calculate scale and bias
        scale = self._climRef.range / r1
        bias = (self._climRef.min - self._clim.min) / r2    
        return scale, bias


class BaseTexture(Wobject):
    """ Base texture class for visvis 2D and 3D textures. """
    
    def __init__(self, parent, data):
        Wobject.__init__(self, parent)
        
        # create texture (remember, this is an abstract class)
        self._texture1 = None
        
        # create colormap
        self._colormap = Colormap()
        
        # create glsl program for this texture...
        self._program1 = program =  GlslProgram()
        
        # scale and translation transforms
        self._trafo_scale = Transform_Scale()
        self._trafo_trans = Transform_Translate()
        self.transformations.append(self._trafo_trans)
        self.transformations.append(self._trafo_scale)        
    
    
    def SetData(self, data):
        """ Set the data to display. """ 
        
        # set data to texture
        self._texture1.SetData(data)
        
        # if Aarray, edit scaling and transform
        if isinstance(data, points.Aarray):
            if hasattr(data,'_sampling') and hasattr(data,'_origin'):
                if isinstance(self, Texture2D):
                    self._trafo_scale.sx = data.sampling[1]
                    self._trafo_scale.sy = data.sampling[0]
                    #
                    self._trafo_trans.dx = data.origin[1]
                    self._trafo_trans.dy = data.origin[0]
                elif isinstance(self, Texture3D):        
                    self._trafo_scale.sx = data.sampling[2]
                    self._trafo_scale.sy = data.sampling[1]
                    self._trafo_scale.sz = data.sampling[0]
                    #
                    self._trafo_trans.dx = data.origin[2]
                    self._trafo_trans.dy = data.origin[1]
                    self._trafo_trans.dz = data.origin[0]
    
    
    def Refresh(self):
        """ Refresh the data. """
        data = self._texture1._dataRef
        if data is not None:
            self._texture1.SetData(data)
   
    
    def OnDestroyGl(self):
        """ Clean up OpenGl resources. """
        
        # remove texture from opengl memory
        self._texture1.DestroyGl()
        
        # clear shaders
        self._program1.DestroyGl()
        
        # remove colormap's texture from memory        
        if hasattr(self, '_colormap'):
            self._colormap.DestroyGl()
    
    
    def OnDestroy(self):
        """ Clean up any resources. """
        # clean up thorougly
        self._texture1.Destroy()
        if hasattr(self, '_colormap'):
            self._colormap.Destroy()
    
    
    def OnDrawFast(self):
        self.OnDraw(True)
    
    
    @Property
    def interpolate():
        """ Interpolate the image when zooming in (using linear interpolation).
        """
        def fget(self):
            return self._texture1._interpolate
        def fset(self, value):
            self._texture1._interpolate = bool(value)
            # bind the texture
            texType = self._texture1._texType            
            gl.glBindTexture(texType, self._texture1._texId)
            # set interpolation
            tmp = {False:gl.GL_NEAREST, True:gl.GL_LINEAR}[bool(value)]
            gl.glTexParameteri(texType, gl.GL_TEXTURE_MAG_FILTER, tmp)
    
    
    @Property
    def colormap():
        """ Get/Set the colormap. The argument must be a tuple/list of 
        iterables with each element having 3 or 4 values. The argument may
        also be a Nx3 or Nx4 numpy array. In both cases the data is resampled
        to create a 256x4 array.
        """
        def fget(self):
            return self._colormap.GetMap()
        def fset(self, value):
            self._colormap.SetMap(value)
    
    @Property
    def clim():
        """ Get/Set the contrast limits. For a gray colormap, clim.min is black,
        clim.max is white.
        """
        def fget(self):
            return self._texture1._clim
        def fset(self, value):
            if not isinstance(value, Range):
                value = Range(value)
            self._texture1._clim = value
    
    
    def SetClim(self, *minmax):
        """ Set the contrast limits. Different than the property clim, this
        re-uploads the texture using different transfer functions. You should
        use this if your data has a higher contrast resolution than 8 bits.
        Takes a bit more time than clim though (which basically takes no
        time at all).
        """
        if len(minmax)==0:
            # set default values
            data = self._texture1._dataRef
            if data is None:
                return 
            minmax = data.min(), data.max()
        
        elif len(minmax)==1:
            # a range was given
            minmax = minmax[0]
            
        # Set climref and clim
        self._texture1._climRef.Set(minmax[0], minmax[1])
        self._texture1._clim.Set(minmax[0], minmax[1])
        
        # Clear texture, on next draw, it is uploaded again, using
        # the newly set climref.
        self._texture1.DestroyGl()
    



class Texture2D(BaseTexture):
    """ A data type that represents structured data in
    two dimensions (an image). Supports grayscale, RGB, 
    and RGBA images.
    """
    
    def __init__(self, parent, data):
        BaseTexture.__init__(self, parent, data)
        
        # create texture and set data
        self._texture1 = TextureObjectToVisualize(gl.GL_TEXTURE_2D, data)
        self.SetData(data)
        
#         # register upload and update callbacks
#         self._texture1.updateCallback = self._OnUpdate
#         self._texture1.uploadCallback = self._OnUpload
        
        # init antialiasing
        self._aa = 0
    
    
    def _CreateGaussianKernel(self):
        """ Create kernel values to use in the aa program.
        Returns 4 element list which should be applied using the
        following indices: 3 2 1 0 1 2 3
        """
        
        figure = self.GetFigure()
        axes = self.GetAxes()
        if not figure or not axes:
            return 1,0,0,0
        
        # determine relative kernel size
        w,h = figure.GetSize()
        cam = axes.camera
        sx = (cam.view_zoomx / 1.0 ) / w
        sy = (cam.view_zoomy / 1.0 ) / h
        # correct for fact that humans prefer sharpness
        tmp = 0.7
        sx, sy = sx*tmp, sy*tmp
        
        # keep >= 0 so we can devide
        if sx<0.01: sx = 0.01
        if sy<0.01: sy = 0.01
        
        # calculate kernel
        #  3 2 1 0 1 2 3
        k = [1.0,0,0,0] 
        k[1] = math.exp( -1.0 / (2*sx**2) )
        k[2] = math.exp( -2.0 / (2*sy**2) )
        k[3] = math.exp( -3.0 / (2*sy**2) )
        
        # normalize
        if self.aa == 1:
            l = k[0] + 2*k[1]
        elif self.aa == 2:
            l = k[0] + 2*k[1] + 2*k[2]
        elif self.aa == 3:
            l = k[0] + 2*k[1] + 2*k[2] + 2*k[3]
        else:
            l = k[0]
        k = [e/l for e in k]
        
        # done!        
        return k
    
    
    def OnDrawShape(self, clr):
        """ Implementation of the OnDrawShape method.
        Defines the texture's shape as a rectangle.
        """        
        gl.glColor(clr[0], clr[1], clr[2], 1.0)
        self._DrawQuads()
    

    def OnDraw(self, fast=False):
        """ Draw the texture.
        """
        
        # set color to white, otherwise with no shading, there is odd scaling
        gl.glColor3f(1.0,1.0,1.0)
        
        # draw texture also from beneeth
        #gl.glCullFace(gl.GL_FRONT_AND_BACK)
        
        # enable texture
        self._texture1.Enable(0)
        
        # _texture._shape is a good indicator of a valid texture
        if not self._texture1._shape:
            return
        
        # fragment shader on
        if self._program1.IsUsable():
            self._program1.Enable()
            # textures        
            self._program1.SetUniformi('texture', [0])        
            self._colormap.Enable(1)
            self._program1.SetUniformi('colormap', [1])
            # uniform variables
            shape = self._texture1._shape # how it is in opengl
            k = self._CreateGaussianKernel()
            self._program1.SetUniformf('kernel', k)
            self._program1.SetUniformf('dx', [1.0/shape[0]])
            self._program1.SetUniformf('dy', [1.0/shape[1]])
            self._program1.SetUniformf('scaleBias', self._texture1._ScaleBias_get())
            self._program1.SetUniformi('applyColormap', [len(shape)==2])
        
        # do the drawing!
        self._DrawQuads()
        gl.glFlush()
        
        # clean up
        self._texture1.Disable()
        self._colormap.Disable()
        self._program1.Disable()
    
    
    def _DrawQuads(self):
        """ Draw the quads of the texture. 
        This is done in a seperate method to reuse code in 
        OnDraw() and OnDrawShape(). """        
        if not self._texture1._shape:
            return        
        
        # The -0.5 offset is to center pixels/voxels. This works correctly
        # for anisotropic data.
        x1, x2 = -0.5, self._texture1._shape[1]-0.5
        y2, y1 = -0.5, self._texture1._shape[0]-0.5
        
        # draw
        gl.glBegin(gl.GL_QUADS)
        gl.glTexCoord2f(0,0); gl.glVertex3d(x1, y2, 0.0)
        gl.glTexCoord2f(1,0); gl.glVertex3d(x2, y2, 0.0)
        gl.glTexCoord2f(1,1); gl.glVertex3d(x2, y1, 0.0)
        gl.glTexCoord2f(0,1); gl.glVertex3d(x1, y1, 0.0)
        gl.glEnd()
    
    
    
    @Property
    def aa():
        """ Set anti aliasing.
        0 or False for no anti aliasing
        1 for minor anti aliasing
        2 for medium anti aliasing
        3 for much anti aliasing
        a string to chose a shader (to allow home-made shaders)
        """
        def fget(self):
            return self._aa
        def fset(self, value):
            if not value:
                value = 0
            if isinstance(value, (int,float)):
                if value < 0 or value > 3:
                    print "Texture2D.aa: value should be 0,1,2,3 or a string."
                    return
                self._aa = value
                if self._aa == 1:
                    self._program1.SetFragmentShader(fshaders['aa1'])
                elif self._aa == 2:
                    self._program1.SetFragmentShader(fshaders['aa1'])
                elif self._aa == 3:
                    self._program1.SetFragmentShader(fshaders['aa1'])
                else:
                    self._program1.SetFragmentShader(fshaders['aa0'])
            elif isinstance(value, basestring):
                if value in fshaders:
                    self._program1.SetFragmentShader(fshaders[value])
                else:
                    print "Texture2D.aa: unknown shader, no action taken."
            else:
                raise ValueError("Texture2D.aa accepts integer or string.")
    

class Texture3D(BaseTexture):
    """ A data type that represents structured data in
    three dimensions (a volume).
    """
    
    def __init__(self, parent, data, renderStyle='mip'):
        BaseTexture.__init__(self, parent, data)
        
        # create texture and set data
        self._texture1 = TextureObjectToVisualize(gl.GL_TEXTURE_3D, data)
        self.SetData(data)
        
#         # register upload and update callbacks
#         self._texture1.updateCallback = self._OnUpdate
#         self._texture1.uploadCallback = self._OnUpload
        
        # init interpolation
        self._texture1._interpolate = True # looks so much better
        
        # init iso shader param
        self._isoThreshold = 0.0
        
        # init vertex shader
        self._program1.SetVertexShader(vshaders['calculateray'])
        # init fragment shader, be robust if user gives invalid method
        self._renderStyle = ''
        self.renderStyle = renderStyle
        if not self._renderStyle:
            self.renderStyle = 'mip'
        
        # attribut to store array of quads (vertices and texture coords)
        self._quads = None
    
    
    
    
    
    
    def OnDrawShape(self, clr):
        """ Implementation of the OnDrawShape method.
        Defines the texture's shape as a rectangle.
        """
        gl.glColor(clr[0], clr[1], clr[2], 1.0)        
        self._DrawQuads()
    
    
    def OnDraw(self, fast=False):
        """ Draw the texture.
        """
        
        # enable this texture
        self._texture1.Enable(0)
        
        # _texture._shape is a good indicator of a valid texture
        if not self._texture1._shape:
            return
        
        # Prepare by setting things to their defaults. This might release some
        # memory so result in a bigger chance that the shader is run in 
        # hardware mode. On ATI, the line and point smoothing should be off
        # if you want to use gl_FragCoord. (Yeah, I do not see the connection
        # either...)
        gl.glPointSize(1)
        gl.glLineWidth(1)
        gl.glDisable(gl.GL_LINE_STIPPLE)
        gl.glDisable(gl.GL_LINE_SMOOTH)
        gl.glDisable(gl.GL_POINT_SMOOTH)
        
        # only draw front-facing parts
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glCullFace(gl.GL_BACK)
        
        # fragment shader on
        if self._program1.IsUsable():
            self._program1.Enable()
            
            # bind texture- and help-textures (create if it does not exist)
            self._program1.SetUniformi('texture', [0])        
            self._colormap.Enable(1)
            self._program1.SetUniformi('colormap', [1])
            
            # set uniforms: parameters
            shape = self._texture1._shape # as in opengl
            self._program1.SetUniformf('shape',reversed(list(shape)) )
            ran = self._texture1._climRef.range
            if ran==0:
                ran = 1.0
            th = (self._isoThreshold - self._texture1._climRef.min ) / ran
            self._program1.SetUniformf('th', [th]) # in 0:1
            if fast:
                self._program1.SetUniformf('stepRatio', [0.4])
            else:
                self._program1.SetUniformf('stepRatio', [1.0])
            self._program1.SetUniformf('scaleBias', self._texture1._ScaleBias_get())        
        
        # do the actual drawing
        self._DrawQuads()
        
        # clean up
        gl.glFlush()        
        self._texture1.Disable()
        self._colormap.Disable()
        self._program1.Disable()
        #
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_LINE_SMOOTH)
        gl.glEnable(gl.GL_POINT_SMOOTH)
    
    
    def _CreateQuads(self):
        
        axes = self.GetAxes()
        if not axes:
            return
        
        # Note that we could determine the world coordinates and use
        # them directly here. However, the way that we do it now (using
        # the transformations) is to be preferred, because that way the
        # transformations are applied via the ModelView matrix stack,
        # and can easily be made undone in the raycaster.
        # The -0.5 offset is to center pixels/voxels. This works correctly
        # for anisotropic data.
        x0,x1 = -0.5, self._texture1._shape[2]-0.5
        y0,y1 = -0.5, self._texture1._shape[1]-0.5
        z0,z1 = -0.5, self._texture1._shape[0]-0.5
        
        # prepare texture coordinates
        t0, t1 = 0, 1
        
        # if any axis are flipped, make sure the correct polygons are front
        # facing
        tmp = 1
        for i in axes.daspect:
            if i<0:
                tmp*=-1        
        if tmp==1:
            t0, t1 = t1, t0
            x0, x1 = x1, x0
            y0, y1 = y1, y0
            z0, z1 = z1, z0
        
        # using glTexCoord* is the same as glMultiTexCoord*(GL_TEXTURE0)
        # Therefore we need to bind the base texture to 0.
        
        # draw. So we draw the six planes of the cube (well not a cube,
        # a 3d rectangle thingy). The inside is only rendered if the 
        # vertex is facing front, so only 3 planes are rendered at a        
        # time...                
        
        tex_coord, ver_coord = points.Pointset(3), points.Pointset(3)
        indices = [0,1,2,3, 4,5,6,7, 3,2,6,5, 0,4,7,1, 0,3,5,4, 1,7,6,2]
        
        # bottom
        tex_coord.Append((t0,t0,t0)); ver_coord.Append((x0, y0, z0)) # 0
        tex_coord.Append((t1,t0,t0)); ver_coord.Append((x1, y0, z0)) # 1
        tex_coord.Append((t1,t1,t0)); ver_coord.Append((x1, y1, z0)) # 2
        tex_coord.Append((t0,t1,t0)); ver_coord.Append((x0, y1, z0)) # 3
        # top
        tex_coord.Append((t0,t0,t1)); ver_coord.Append((x0, y0, z1)) # 4    
        tex_coord.Append((t0,t1,t1)); ver_coord.Append((x0, y1, z1)) # 5
        tex_coord.Append((t1,t1,t1)); ver_coord.Append((x1, y1, z1)) # 6
        tex_coord.Append((t1,t0,t1)); ver_coord.Append((x1, y0, z1)) # 7
#         # front
#         tex_coord.Append((t0,t1,t0)); ver_coord.Append((x0, y1, z0))
#         tex_coord.Append((t1,t1,t0)); ver_coord.Append((x1, y1, z0))
#         tex_coord.Append((t1,t1,t1)); ver_coord.Append((x1, y1, z1))
#         tex_coord.Append((t0,t1,t1)); ver_coord.Append((x0, y1, z1))
#         # back
#         tex_coord.Append((t0,t0,t0)); ver_coord.Append((x0, y0, z0))
#         tex_coord.Append((t0,t0,t1)); ver_coord.Append((x0, y0, z1))
#         tex_coord.Append((t1,t0,t1)); ver_coord.Append((x1, y0, z1))
#         tex_coord.Append((t1,t0,t0)); ver_coord.Append((x1, y0, z0))        
#         # left
#         tex_coord.Append((t0,t0,t0)); ver_coord.Append((x0, y0, z0))
#         tex_coord.Append((t0,t1,t0)); ver_coord.Append((x0, y1, z0))
#         tex_coord.Append((t0,t1,t1)); ver_coord.Append((x0, y1, z1))
#         tex_coord.Append((t0,t0,t1)); ver_coord.Append((x0, y0, z1))
#         # right
#         tex_coord.Append((t1,t0,t0)); ver_coord.Append((x1, y0, z0))
#         tex_coord.Append((t1,t0,t1)); ver_coord.Append((x1, y0, z1))
#         tex_coord.Append((t1,t1,t1)); ver_coord.Append((x1, y1, z1))
#         tex_coord.Append((t1,t1,t0)); ver_coord.Append((x1, y1, z0))
        # 
        
        # store quad arrays
#         tex_coord = np.array(tex_coord, dtype='float32')
#         ver_coord = np.array(ver_coord, dtype='double')
#         self._quads = (tex_coord, ver_coord, None)
        self._quads = (tex_coord, ver_coord, np.array(indices,dtype=np.uint8))
    
    
    def _DrawQuads(self):
        """ Draw the quads of the texture. 
        This is done in a seperate method to reuse code in 
        OnDraw() and OnDrawShape(). """        
        
        # should we draw?
        if not self._texture1._shape:
            return 
        
        # should we create quads?
        if not self._quads:
            self._CreateQuads()
        
        # get data
        tex_coord, ver_coord, ind = self._quads
        
        # init vertex and texture array
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY)
        gl.glEnableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        gl.glVertexPointerf(ver_coord.data)
        gl.glTexCoordPointerf(tex_coord.data)
        
        # draw
        gl.glDrawElements(gl.GL_QUADS, len(ind), gl.GL_UNSIGNED_BYTE, ind)
        #gl.glDrawArrays(gl.GL_QUADS, 0, len(tex_coord)
        
        # disable vertex array        
        gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY)
    
    
    # todo: remove this as soon as I've verified the new method works for OpenGl <2.0
    def _DrawQuads_old(self):
        """ Draw the quads of the texture. 
        This is done in a seperate method to reuse code in 
        OnDraw() and OnDrawShape(). """        
        if not self._texture1._shape:
            return 
        
        # prepare world coordinates
        x0,x1 = -0.5, self._texture1._shape[2]-0.5
        y0,y1 = -0.5, self._texture1._shape[1]-0.5
        z0,z1 = -0.5, self._texture1._shape[0]-0.5
        
        # prepare texture coordinates
        t0, t1 = 0, 1        
        # if any axis are flipped, make sure the correct polygons are front
        # facing
        tmp = 1
        for i in self.GetAxes().daspect:
            if i<0:
                tmp*=-1        
        if tmp==1:
            t0, t1 = t1, t0
            x0, x1 = x1, x0
            y0, y1 = y1, y0
            z0, z1 = z1, z0
        
        # using glTexCoord* is the same as glMultiTexCoord*(GL_TEXTURE0)
        # Therefore we need to bind the base texture to 0.
        
        # draw. So we draw the six planes of the cube (well not a cube,
        # a 3d rectangle thingy). The inside is only rendered if the 
        # vertex is facing front, so only 3 planes are rendered at a        
        # time...                
        gl.glBegin(gl.GL_QUADS)
        # bottom
        gl.glTexCoord3f(t0,t0,t0); gl.glVertex3d(x0, y0, z0)
        gl.glTexCoord3f(t1,t0,t0); gl.glVertex3d(x1, y0, z0)
        gl.glTexCoord3f(t1,t1,t0); gl.glVertex3d(x1, y1, z0)
        gl.glTexCoord3f(t0,t1,t0); gl.glVertex3d(x0, y1, z0)
        # top
        gl.glTexCoord3f(t0,t0,t1); gl.glVertex3d(x0, y0, z1)        
        gl.glTexCoord3f(t0,t1,t1); gl.glVertex3d(x0, y1, z1)
        gl.glTexCoord3f(t1,t1,t1); gl.glVertex3d(x1, y1, z1)
        gl.glTexCoord3f(t1,t0,t1); gl.glVertex3d(x1, y0, z1)
        # front
        gl.glTexCoord3f(t0,t1,t0); gl.glVertex3d(x0, y1, z0)
        gl.glTexCoord3f(t1,t1,t0); gl.glVertex3d(x1, y1, z0)
        gl.glTexCoord3f(t1,t1,t1); gl.glVertex3d(x1, y1, z1)
        gl.glTexCoord3f(t0,t1,t1); gl.glVertex3d(x0, y1, z1)
        # back
        gl.glTexCoord3f(t0,t0,t0); gl.glVertex3d(x0, y0, z0)
        gl.glTexCoord3f(t0,t0,t1); gl.glVertex3d(x0, y0, z1)
        gl.glTexCoord3f(t1,t0,t1); gl.glVertex3d(x1, y0, z1)
        gl.glTexCoord3f(t1,t0,t0); gl.glVertex3d(x1, y0, z0)        
        # left
        gl.glTexCoord3f(t0,t0,t0); gl.glVertex3d(x0, y0, z0)
        gl.glTexCoord3f(t0,t1,t0); gl.glVertex3d(x0, y1, z0)
        gl.glTexCoord3f(t0,t1,t1); gl.glVertex3d(x0, y1, z1)
        gl.glTexCoord3f(t0,t0,t1); gl.glVertex3d(x0, y0, z1)
        # right
        gl.glTexCoord3f(t1,t0,t0); gl.glVertex3d(x1, y0, z0)
        gl.glTexCoord3f(t1,t0,t1); gl.glVertex3d(x1, y0, z1)
        gl.glTexCoord3f(t1,t1,t1); gl.glVertex3d(x1, y1, z1)
        gl.glTexCoord3f(t1,t1,t0); gl.glVertex3d(x1, y1, z0)
        # 
        gl.glEnd()
    
    
    @Property
    def renderStyle():
        """ Get or set the render style to render the volumetric data:
            - mip: maximum intensity projection
            - iso: isosurface rendering
            - rays: ray casting
        """
        def fget(self):
            return self._renderStyle
        def fset(self, style):            
            style = style.lower()
            # first try directly
            if style in fshaders:
                self._renderStyle = style
                self._program1.SetFragmentShader(fshaders[style])
            # then try aliases
            elif style in ['mip']:
                self._renderStyle = 'mip'
                self._program1.SetFragmentShader(fshaders['mip'])
            elif style in ['iso', 'isosurface']:
                self._renderStyle = 'isosurface'
                self._program1.SetFragmentShader(fshaders['isosurface'])
            elif style in ['ray', 'rays', 'raycasting']:
                self._renderStyle = 'raycasting'
                self._program1.SetFragmentShader(fshaders['raycasting'])
            else:
                print "Unknown render style in Texture3d.renderstyle."

    @Property
    def isoThreshold():
        def fget(self):
            return self._isoThreshold
        def fset(self, value):
            # make float
            value = float(value)
            # store
            self._isoThreshold = value


class MultiTexture3D(Texture3D):
    """ MultiTexture3D(parent, data1, data2)
    This is an example of what multi-texturing would look like
    in Visvis. Not tested.
    """
    
    def __init__(self, parent, data1, data2):
        Texture3D.__init__(self, parent, data1)
        
        # create second texture and set data
        self._texture2 = TextureObject(gl.GL_TEXTURE_3D)
        self.SetData(data2)
    
    
    def OnDraw(self, fast=False):
        """ Draw the texture.
        """
        
        # enable textures
        self._texture1.Enable(0)
        self._texture2.Enable(0)
        
        # _texture._shape is a good indicator of a valid texture
        if not self._texture1._shape or not self._texture2._shape:
            return
        
        # Prepare by setting things to their defaults. This might release some
        # memory so result in a bigger chance that the shader is run in 
        # hardware mode. On ATI, the line and point smoothing should be off
        # if you want to use gl_FragCoord. (Yeah, I do not see the connection
        # either...)
        gl.glPointSize(1)
        gl.glLineWidth(1)
        gl.glDisable(gl.GL_LINE_STIPPLE)
        gl.glDisable(gl.GL_LINE_SMOOTH)
        gl.glDisable(gl.GL_POINT_SMOOTH)
        
        # only draw front-facing parts
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glCullFace(gl.GL_BACK)
        
        # fragment shader on
        if self._program1.IsUsable():
            self._program1.Enable()
            
            # bind texture- and help-textures (create if it does not exist)
            self._program1.SetUniformi('texture', [0])        
            self._colormap.Enable(1)
            self._program1.SetUniformi('colormap', [1])
            
            # set uniforms: parameters
            shape = self._texture1._shape # as in opengl
            self._program1.SetUniformf('shape',reversed(list(shape)) )
            ran = self._climRef.range
            if ran==0:
                ran = 1.0
            th = (self._isoThreshold - self._climRef.min ) / ran
            self._program1.SetUniformf('th', [th]) # in 0:1
            if fast:
                self._program1.SetUniformf('stepRatio', [0.4])
            else:
                self._program1.SetUniformf('stepRatio', [1.0])
            self._program1.SetUniformf('scaleBias', self._ScaleBias_get())        
        
        # do the actual drawing
        self._DrawQuads()
        
        # clean up
        gl.glFlush()        
        self._texture1.Disable()
        self._texture2.Disable()
        self._colormap.Disable()
        self._program1.Disable()
        #
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_LINE_SMOOTH)
        gl.glEnable(gl.GL_POINT_SMOOTH)


    def OnDestroyGl(self):
        """ Clean up OpenGl resources. """
        
        # remove texture from opengl memory
        self._texture1.DestroyGl()
        self._texture2.DestroyGl()
        
        # clear shaders
        self._program1.DestroyGl()
        
        # remove colormap's texture from memory        
        if hasattr(self, '_colormap'):
            self._colormap.DestroyGl()
    
    
    def OnDestroy(self):
        """ Clean up any resources. """
        # clean up thorougly
        self._texture1.Destroy()
        self._texture2.Destroy()
        if hasattr(self, '_colormap'):
            self._colormap.Destroy()

