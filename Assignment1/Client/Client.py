from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk, ImageFilter, ImageEnhance
import socket, threading, sys, traceback, platform, io, time

from RtpPacket import RtpPacket

# CACHE_FILE_NAME = "cache-"
# CACHE_FILE_EXT = ".jpg"

#NOTE: rmb to close rtsp socket (the exit logic) => DONE!
#NOTE: implement a buffer (queue)?
#NOTE: implement the preview when scrolling
#NOTE: what if the packets are lost? (currently assuming no losses)
#LESSON LEARNT: we have to make sure that the state on Client and ServerWorker are the same at everytime

class Client:
    INIT = 0
    READY = 1
    PLAYING = 2
    SWITCHING = 3
    TORNDOWN = 4
    state = INIT
    
    SETUP = 0
    PLAY = 1
    PAUSE = 2
    TEARDOWN = 3
    DESCRIBE = 4
    SWITCH = 5
    CLOSE = 6
    SPEED = 7
    ADD = 8
    
    # Initiation..
    def __init__(self, master, serveraddr, serverport, rtpport, filename):
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.handler)

        if platform.system() == 'Windows':
            self.describeText = 'Describe ⓘ'
            self.playText = 'Play ▶'
            self.pauseText = 'Pause ⏸'
            self.switchText = 'Switch 💩'
            self.stopText = 'Stop ■'
        elif platform.system() == 'Linux': # linux host having font issue
            self.describeText = 'Describe'
            self.playText = 'Play'
            self.pauseText = 'Pause'
            self.switchText = 'Switch'
            self.stopText = 'Stop'
        self.speedTexts = ['x2', 'Normal', 'x0.5']

        # for listenRtp
        self.interrupt = threading.Event()

        # playback speed
        self.speedText = StringVar()
        self.frameNbr = IntVar()
        self.totalFrameNbr = 0
        self.elapsedTime = StringVar(value='00:00')
        self.remainingTime = StringVar(value='00:00')
        self.playPauseText = StringVar(value=self.playText)
        self.serverAddr = serveraddr
        self.serverPort = int(serverport)
        self.rtpPort = int(rtpport)
        self.fileName = filename
        self.createWidgets()
        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = 0
        self.teardownAcked = 0
        self.connectToServer()
        # width and height of the video
        self.width = 0
        self.height = 0
        # SETUP is mandatory in an RTSP interaction
        self.setupMovie()
        # for the scrollbar
        self.scroll = False
        # to calculate packet lost rate
        self.receivedNo = 0
        # to handle invalid youtube link
        self.adding = False

        def forward5s(event):
            oldState = self.state
            self.pauseMovie()
            self.frameNbr.set(self.frameNbr.get()+100)
            if self.frameNbr.get() == self.totalFrameNbr-1:
                # buttons' states
                self.playPause["state"] = DISABLED
            elif oldState == self.PLAYING:
                self.playMovie()

        def backward5s(event):
            oldState = self.state
            self.pauseMovie()
            self.frameNbr.set(self.frameNbr.get()-100)
            if oldState == self.PLAYING:
                self.playMovie()
            if self.playPause["state"] == DISABLED:
                self.playPause["state"] = NORMAL

        self.master.bind('<Right>', forward5s)
        self.master.bind('<Left>', backward5s)
        self.master.bind('<space>', self.playPauseMovie)
        self.master.bind('<Escape>', self.handler)
        
    # THIS GUI IS JUST FOR REFERENCE ONLY, STUDENTS HAVE TO CREATE THEIR OWN GUI     
    def createWidgets(self):
        """Build GUI."""
        # Create a label to display the movie
        # dummy photo
        photo = ImageTk.PhotoImage(data=bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010100000000376ef9240000000a49444154789c636000000002000148afa4710000000049454e44ae426082'))
        self.label = Label(self.master, height=275, image=photo,
                           bg="black", relief='ridge', bd=2)
        self.label.image = photo
        self.label.grid(row=0, column=0, columnspan=5, sticky=W+E+N+S, padx=5, pady=5)

        # Create a label to display the elapsed time
        self.eTimeLabel = Label(self.master, anchor=W, width=12, padx=3, pady=3, bg="white")
        self.eTimeLabel["textvariable"] = self.elapsedTime
        self.eTimeLabel.grid(row=1, column=0, padx=2, pady=2)

        # Create a label to display the remaining time
        self.eTimeLabel = Label(self.master, anchor=E, width=12, padx=3, pady=3, bg="white")
        self.eTimeLabel["textvariable"] = self.remainingTime
        self.eTimeLabel.grid(row=1, column=4, padx=2, pady=2)

        # Create Describe button
        self.describe = Button(self.master, width=10, padx=7, pady=3)
        self.describe["text"] = self.describeText
        self.describe["command"] = self.describeMovie
        self.describe.grid(row=2, column=0, padx=7, pady=2)

        # Create Switch button
        self.switch = Button(self.master, width=10, padx=7, pady=3)
        self.switch["text"] = self.switchText
        self.switch["command"] = self.switchMovie
        self.switch.grid(row=2, column=1, padx=7, pady=2)

        # Create Play/Pause button
        self.playPause = Button(self.master, width=20, padx=7, pady=3)
        self.playPause["textvariable"] = self.playPauseText
        self.playPause["command"] = self.playPauseMovie
        self.playPause.grid(row=2, column=2, padx=7, pady=2)

        # Create Speed button
        self.speed = OptionMenu(self.master, self.speedText, *self.speedTexts,
                                command=self.changeSpeedMovie)
        self.speed.config(width=7, padx=7, pady=3,
                          direction='above', relief='raised', bd=2)
        self.speed.grid(row=2, column=3, padx=7, pady=2)
        
        # Create Stop button
        self.stop = Button(self.master, width=10, padx=7, pady=3)
        self.stop["text"] = self.stopText
        self.stop["command"] =  self.stopMovie
        self.stop.grid(row=2, column=4, padx=7, pady=2)
    
    def setupMovie(self):
        """Setup function handler."""
        if self.state == self.INIT or self.state == self.SWITCHING:
            self.sendRtspRequest(self.SETUP)
            data = self.recvRtspReply()
            if not self.parseRtspReply(data):
                return

            self.label.update()
            ratio = min(self.label.winfo_width()/self.width, self.label.winfo_height()/self.height)
            self.width = int(self.width * ratio)
            self.height = int(self.height * ratio)

            # for the mini preview
            self.rightBound = 2*self.label.winfo_x()+self.label.winfo_width()-7-self.width//3-4 # 4 == 2 * self.scrollbar["bd"]

            if self.state == self.INIT:

                def spress(event):
                    if self.state != self.SWITCHING and self.state != self.TORNDOWN:
                        # The scale's position
                        self.frameNbr.set(min(self.totalFrameNbr-1, max(0, (event.x-self.scrollbar["sliderlength"]/2) / (self.scrollbar["length"]-self.scrollbar["sliderlength"]) * (self.totalFrameNbr-1))))
                        # Small preview
                        self.preview = Label(self.master, height=92, bg="gray", bd=2)
                        self.scroll = True

                        try: # scroll before everything
                            self.rtpSocket
                        except:
                            self.playMovie()
                            self.pauseMovie()

                        #self.rtpSocket = self.openRtpPort(None)
                        self.interrupt.set()
                        self.interrupt.clear()
                        self.worker = threading.Thread(target=self.listenRtp)
                        self.worker.start()

                        self.sendRtspRequest(self.PAUSE, timeout='0')
                        data = self.recvRtspReply()
                        self.parseRtspReply(data)

                        self.sendRtspRequest(self.PLAY, timeout='0')
                        data = self.recvRtspReply()
                        self.parseRtspReply(data)

                def scroll(event):
                    if self.state != self.SWITCHING and self.state != self.TORNDOWN and self.scroll:
                        self.sendRtspRequest(self.PLAY, timeout='0')
                        data = self.recvRtspReply()
                        self.parseRtspReply(data)
                
                def srelease(event):
                    if self.state != self.SWITCHING and self.state != self.TORNDOWN and self.scroll:
                        self.scroll = False
                        self.preview.destroy()

                        if self.state == self.READY:
                            self.sendRtspRequest(self.PAUSE, timeout='1')
                        elif self.state == self.PLAYING: # the become READY on the server
                            self.sendRtspRequest(self.PAUSE, timeout='2')
                        data = self.recvRtspReply()
                        self.parseRtspReply(data)

                        # close the socket
                        self.interrupt.set()
                        #self.rtpSocket.settimeout(0.001)
                        #self.rtpSocket.shutdown(socket.SHUT_RDWR) # stop `recvfrom` function in `listenRtp` => would trigger self.rtpSocket.close()
                        #self.rtpSocket.close()

                        # buttons' states
                        if self.playPause["state"] == DISABLED:
                            self.playPause["state"] = NORMAL
                            
                        if self.state == self.PLAYING:
                            self.state = self.READY
                            self.playMovie()
                        else:
                            # HOW TO CLOSE THIS THREAD???
                            # (??) => no need cuz it'll be overwritten eventually by openRtpPort
                            #self.worker.join()

                            # undo the dark blurred image
                            image = Image.open(io.BytesIO(self.data))
                            image = image.resize((self.width, self.height), Image.ANTIALIAS)
                            photo = ImageTk.PhotoImage(image)
                            for _ in range(2):
                                self.label.configure(image=photo, height=275)
                                self.label.image = photo

                self.scrollbar = Scale(self.master, from_=0, to=self.totalFrameNbr-1,
                                       length=self.master.winfo_width()*0.8, orient=HORIZONTAL,
                                       showvalue=0, sliderlength=15,
                                       activebackground="red", bg="gray", troughcolor="black")
                self.scrollbar["variable"] = self.frameNbr
                # self.scrollbar.bind("<Button-1>", press)
                # self.scrollbar.bind("<ButtonRelease-1>", release)
                self.scrollbar.bind("<Button-1>", spress)
                self.scrollbar["command"] = scroll
                self.scrollbar.bind("<ButtonRelease-1>", srelease)
                self.scrollbar.grid(row=1, column=0, columnspan=5, padx=2, pady=2)
            elif self.state == self.SWITCHING:
                self.scrollbar["variable"] = self.frameNbr
                self.scrollbar.set(0)
                self.scrollbar["to"] = self.totalFrameNbr-1

            self.state = self.READY
            self.interrupt.clear()
            self.processingInterval = 0

            # for the speed button
            self.speedText.set(self.speedTexts[1])
            self.oldSpeedText = self.speedTexts[1]
            # Set the playback speed to normal
            self.waitInterval = 0.05

    def describeMovie(self):
        """Describe function handler."""
        self.sendRtspRequest(self.DESCRIBE)
        data = self.recvRtspReply()
        self.parseRtspReply(data)
    
    def playMovie(self):
        """Play button handler."""
        if self.state != self.TORNDOWN and self.state == self.READY:
            self.sendRtspRequest(self.PLAY)
            #NOTE: open the port here to decrease the lost datagram numbers
            #if we open after parsing, we can open after when the server have sent the first frame
            self.rtpSocket = self.openRtpPort()
            data = self.recvRtspReply()
            if self.parseRtspReply(data):
                # buttons' style
                self.playPauseText.set(self.pauseText)
                # Create a new thread and start receiving RTP packets
                self.interrupt.clear()
                self.worker = threading.Thread(target=self.listenRtp)
                self.worker.start()
                self.state = self.PLAYING

    def pauseMovie(self):
        """Pause button handler."""
        if self.state != self.TORNDOWN and self.state == self.PLAYING:
            self.interrupt.set()
            self.sendRtspRequest(self.PAUSE)
            data = self.recvRtspReply()
            if self.parseRtspReply(data):
                # buttons' style
                self.playPauseText.set(self.playText)
                self.state = self.READY

    def playPauseMovie(self, event=''):
        print(self.playPause['state'])
        if self.playPause['state'] != DISABLED:
            """Play/Pause button handler."""
            if self.playPauseText.get() == self.playText:
                self.playMovie()
            elif self.playPauseText.get() == self.pauseText:
                self.pauseMovie()

    def addYTVideo(self, chooseMovie): # assume only valid URL
        self.adding = True
        def download():
            self.sendRtspRequest(self.ADD)
            data = self.recvRtspReply()
            if self.parseRtspReply(data):
                tkinter.messagebox.showinfo('Success', 'Your request has been sent sucessfully. Please wait for us to download it...')
            else:
                tkinter.messagebox.showerror('Error', 'The YouTube link is invalid! Please try again later.')
            chooseMovie.lift()
            addVideo.destroy()
            self.adding = False

        def close():
            addVideo.destroy()
            self.adding = False

        addVideo = Toplevel(chooseMovie)
        addVideo.title('Add video')
        addVideo.protocol("WM_DELETE_WINDOW", close)
        
        label = Label(addVideo, text="Enter a YouTube video's URL:", anchor=W, width=50)
        label.grid(row=0, column=0, padx=2, pady=2)

        # user's input
        self.url = StringVar()
        inputBox = Entry(addVideo, exportselection=0, textvariable=self.url, width=50)
        inputBox.grid(row=1, column=0, padx=2, pady=2)

        label = Label(addVideo, text="Enter the file's name:", anchor=W, width=50)
        label.grid(row=2, column=0, padx=2, pady=2)

        # user's input
        self.videoName = StringVar()
        inputBox = Entry(addVideo, exportselection=0, textvariable=self.videoName, width=50)
        inputBox.grid(row=3, column=0, padx=2, pady=2)

        # Create Add button
        add = Button(addVideo, anchor=CENTER, padx=3, pady=3)
        add["text"] = "Add"
        add["command"] = download
        add.grid(row=4, column=0, padx=2, pady=2)

    def chooseMovie(self):
        def finish():
            if chosen.get() == -1:
                tkinter.messagebox.showerror('Error', 'Please choose a movie!')
                chooseMovie.lift()
            else:
                chooseMovie.destroy()

        chooseMovie = Toplevel(self.master)
        chooseMovie.title('Choose movie')
        chooseMovie.protocol("WM_DELETE_WINDOW", chooseMovie.destroy)
        label = Label(chooseMovie, text="Choose a movie:", anchor=W, width=20)
        label.grid(row=0, column=0, padx=2, pady=2)
        chosen = IntVar(value=-1)
        for i in range(len(self.availableMovies)):
            R = Radiobutton(chooseMovie, text=self.availableMovies[i].split('.')[0], variable=chosen, value=i, anchor=W, width=15)
            R.grid(row=i+1, column=0, padx=2, pady=2)
        
        # Create Add button
        add = Button(chooseMovie, anchor=N+E, padx=3)
        add["text"] = "+"
        add["command"] = lambda : self.addYTVideo(chooseMovie)
        add.grid(row=i+2, column=0, padx=2, pady=2)

        # Create Done button
        done = Button(chooseMovie, anchor=CENTER, padx=3, pady=3)
        done["text"] = "Done"
        done["command"] = finish
        done.grid(row=i+3, column=0, padx=2, pady=2)

        return chooseMovie, chosen

    def switchMovie(self):
        self.interrupt.set()
        self.sendRtspRequest(self.SWITCH)
        data = self.recvRtspReply()
        if self.parseRtspReply(data):
            # in case the user just choose the current movie
            oldState = self.state
            self.state = self.SWITCHING

            self.switch["state"] = DISABLED
            self.playPause["state"] = DISABLED
            self.scrollbar["state"] = DISABLED
            self.speed["state"] = DISABLED
            self.stop["state"] = DISABLED
            self.playPauseText.set(self.playText)

            chooseMovie, chosen = self.chooseMovie()

            self.master.wait_window(chooseMovie)
            self.switch["state"] = NORMAL
            self.playPause["state"] = NORMAL
            self.stop["state"] = NORMAL
            self.scrollbar["state"] = NORMAL
            self.speed["state"] = NORMAL

            if oldState != self.TORNDOWN and chosen.get() != -1 and self.fileName == self.availableMovies[chosen.get()]:
                tkinter.messagebox.showwarning('Same movie', 'You have chosen the same movie again!')
                chosen.set(-1)
            if chosen.get() == -1: # do not choose anything
                self.state = self.READY
                if oldState == self.PLAYING:
                    self.playMovie()
                elif oldState == self.READY:
                    self.playMovie()
                    self.pauseMovie()
            else:
                self.fileName = self.availableMovies[chosen.get()]
                self.master.title("Now streaming " + self.fileName + "...")
                # SETUP is mandatory in an RTSP interaction
                self.setupMovie()

    def stopMovie(self): # WHAT'S THE LOGIC???
        """Stop button handler."""
        self.teardownAcked += 1
        # This command stop the current movie
        if self.state != self.TORNDOWN and (self.state == self.READY or self.state == self.PLAYING):
            self.sendRtspRequest(self.TEARDOWN) # for the server to close the movie file
            data = self.recvRtspReply()
            if self.parseRtspReply(data):
                if self.state == self.PLAYING:
                    # close the socket
                    self.interrupt.set()
                    #self.worker.join() # it will join eventually (?)
                self.state = self.TORNDOWN
                self.playPause["state"] = DISABLED
                self.stop["state"] = DISABLED
                self.scrollbar["state"] = DISABLED
                self.speed["state"] = DISABLED

    def changeSpeedMovie(self, event):
        if event != self.oldSpeedText:
            self.sendRtspRequest(self.SPEED)
            data = self.recvRtspReply()
            if self.parseRtspReply(data):
                self.oldSpeedText = event
                self.waitInterval = 0.025 * 2**(self.speedTexts.index(event))
            else: # there are some errors on server's side
                self.speedText.set(self.oldSpeedText)

    def listenRtp(self):
        """Listen for RTP packets."""
        while True:
            if not self.scroll:
                self.interrupt.wait(self.waitInterval - self.processingInterval/1000000000)
          
            start = time.perf_counter_ns() # best possible precision

            if self.interrupt.isSet():
                print("broken dude")
                self.rtpSocket.close()
                break
            # assume stable network
            try:
                data, _ = self.rtpSocket.recvfrom(1 << 16)
                assert(data)
            except: # timeout
                self.rtpSocket.close()
                break
            else: # receive a packet
                self.receivedNo += 1

            # take less than 0.05 sec to process this
            # packet received sucessfully
            packet = RtpPacket()
            packet.decode(data)
            self.frameNbr.set(packet.seqNum())
            #assert(packet.seqNum() == self.frameNbr.get()) #NOTE: try-except right here to count number of errors ...
            frame = packet.getPayload()
            #self.writeFrame(frame)
            self.updateMovie(frame)

            # for better timing
            self.processingInterval = 0.85*self.processingInterval - 0.15*start
            self.processingInterval += 0.15*time.perf_counter_ns()

    def updateMovie(self, data):
        """Update the image file as video frame in the GUI."""

        if not self.scroll:
            if self.frameNbr.get() == self.totalFrameNbr-1:
                self.pauseMovie()
                # buttons' states
                self.playPause["state"] = DISABLED
                return

            image = Image.open(io.BytesIO(data))
            image = image.resize((self.width, self.height), Image.ANTIALIAS)
            photo = ImageTk.PhotoImage(image)
            self.label.configure(image=photo, height=275)
            self.label.image = photo
        else:
            # Small preview
            self.data = data
            image = Image.open(io.BytesIO(data))
            smallImage = image.resize((self.width//3, self.height//3))

            largeImage = smallImage.resize((self.width, self.height))
            #image brightness enhancer
            darkImage = ImageEnhance.Brightness(largeImage).enhance(0.55)
            photo = ImageTk.PhotoImage(darkImage)
            self.label.configure(image=photo, height=275)
            self.label.image = photo

            try:
                photo = ImageTk.PhotoImage(smallImage)
                self.preview.configure(image=photo, height=92)
                self.preview.image = photo
                self.preview.place(x=min(self.rightBound, max(7, self.scrollbar.winfo_x()+self.scrollbar.coords()[0]-self.width//6)), y=self.scrollbar.winfo_y()-self.height//3-5)
            except: # the moment we release the mouse
                pass

        # Update the times
        self.elapsedTime.set(self.sec2time(int(self.frameNbr.get() * 0.05)))
        self.remainingTime.set(self.sec2time(int((self.totalFrameNbr - self.frameNbr.get()) * 0.05)))

    def connectToServer(self):
        """Connect to the Server. Start a new RTSP/TCP session."""
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.rtspSocket.connect((self.serverAddr, self.serverPort))

    def sendRtspRequest(self, requestCode, timeout=''):
        """Send RTSP request to the server.""" 
        self.rtspSeq += 1
        if requestCode == self.SETUP:
            msg = 'SETUP ' + self.fileName + ' RTSP/1.0\n' +\
                  'CSeq: ' + str(self.rtspSeq) + '\n' +\
                  'Transport: RTP/UDP; client_port= ' + str(self.rtpPort)
        elif requestCode == self.PLAY:
            msg = 'PLAY ' + self.fileName + ' RTSP/1.0\n' +\
                  'CSeq: ' + str(self.rtspSeq) + '\n' +\
                  'Session: ' + str(self.sessionId) + '\n' +\
                  'Frame: ' + str(self.frameNbr.get())
        elif requestCode == self.PAUSE:
            msg = 'PAUSE ' + self.fileName + ' RTSP/1.0\n' +\
                  'CSeq: ' + str(self.rtspSeq) + '\n' +\
                  'Session: ' + str(self.sessionId)
        elif requestCode == self.TEARDOWN:
            msg = 'TEARDOWN ' + self.fileName + ' RTSP/1.0\n' +\
                  'CSeq: ' + str(self.rtspSeq) + '\n' +\
                  'Session: ' + str(self.sessionId)
        elif requestCode == self.DESCRIBE:
            msg = 'DESCRIBE RTSP/1.0\n' +\
                  'CSeq: ' + str(self.rtspSeq) + '\n' +\
                  'Session: ' + str(self.sessionId)
        elif requestCode == self.SWITCH:
            msg = 'SWITCH RTSP/1.0\n' +\
                  'CSeq: ' + str(self.rtspSeq) + '\n' +\
                  'Session: ' + str(self.sessionId)
        elif requestCode == self.CLOSE:
            msg = 'CLOSE RTSP/1.0\n' +\
                  'CSeq: ' + str(self.rtspSeq) + '\n' +\
                  'Session: ' + str(self.sessionId)
        elif requestCode == self.SPEED:
            msg = 'SPEED RTSP/1.0\n' +\
                  'CSeq: ' + str(self.rtspSeq) + '\n' +\
                  'Session: ' + str(self.sessionId) + '\n' +\
                  'Speed: ' + str(self.speedTexts.index(self.speedText.get()))
        elif requestCode == self.ADD:
            msg = 'ADD RTSP/1.0\n' +\
                  'CSeq: ' + str(self.rtspSeq) + '\n' +\
                  'Session: ' + str(self.sessionId) + '\n' +\
                  'URL: ' + self.url.get() + '\n' +\
                  'Name: ' + self.videoName.get()

        if timeout:
            msg += '\nTimeout: ' + timeout
        
        self.rtspSocket.send(msg.encode())

    def recvRtspReply(self):
        """Receive RTSP reply from the server."""
        data = self.rtspSocket.recv(2048).decode()
        print("Response received: " + data)
        self.requestSent += 1
        return data
    
    def parseRtspReply(self, data):
        """Parse the RTSP reply from the server."""
        reply = data.split('\n')
        reply = [line.split(' ') for line in reply]
        if not self.sessionId:
            self.sessionId = int(reply[2][1])
        #NOTE: close the connection if there are errors
        try:
            assert(reply[0][1] == '200')
            assert(int(reply[1][1]) == self.rtspSeq)
            assert(int(reply[2][1]) == self.sessionId)
        except:
            if not self.adding:
                self.rtspSocket.close()
            return False

        if len(reply) == 4:
            if reply[3][0] == 'Description:':
                sentNo = int(reply[3][3])
                msg = 'Stream types: ' + reply[3][1] + '\n' +\
                      'Encoding: ' + reply[3][2] + '\n' +\
                      f'Packets: Sent = {sentNo}, Received = {self.receivedNo}, Lost = {sentNo-self.receivedNo} ({0 if sentNo == 0 else round((sentNo-self.receivedNo)/sentNo,2)}% loss)\n' +\
                      f'Data rate: {round(float(reply[3][4]),2)} B/s'
                tkinter.messagebox.showinfo('Session description', msg)
            elif reply[3][0] == 'Info:':
                self.totalFrameNbr = int(reply[3][1])
                self.width = int(reply[3][2])
                self.height = int(reply[3][3])
            elif reply[3][0] == 'Movies:':
                self.availableMovies = reply[3][1:]

        return True
    
    def openRtpPort(self, timeout=0.5):
        """Open RTP socket binded to a specified port."""
        # Create a new datagram socket to receive RTP packets from the server
        rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        cont = True
        while cont:
            exc = False
            try:
                rtpSocket.bind(('', self.rtpPort)) # only exception at this point
                # Set the timeout value of the socket to 0.5sec
                rtpSocket.settimeout(timeout)
            except: # socket already in use
                exc = True
            else:
                cont = False
            
            if exc:
                try:
                    #self.rtpSocket.shutdown(socket.SHUT_RDWR) # stop `recvfrom` function in `listenRtp` => would trigger self.rtpSocket.close()
                    self.rtpSocket.close()
                except:
                    pass
        return rtpSocket

    def handler(self, event=''):
        """Handler on explicitly closing the GUI window."""
        oldState = self.state
        self.pauseMovie()
        if tkinter.messagebox.askyesno("Quit", "Do you want to quit?"):
            try:
                self.sendRtspRequest(self.CLOSE)
                data = self.recvRtspReply()
                if self.parseRtspReply(data):
                    self.rtspSocket.close()
            except: # if the rtsp socket has been disconnected
                pass
            self.master.destroy()
        elif oldState == self.PLAYING:
            self.playMovie()

    def sec2time(self, sec): # assuming the length is always < 1 hour
        return str(sec//60).rjust(2,'0') + ':' + str(sec%60).rjust(2,'0')
