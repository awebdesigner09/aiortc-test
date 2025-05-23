document.addEventListener('DOMContentLoaded', () => {
    const joinButton = document.getElementById('join-button');
    const muteButton = document.getElementById('mute-button');
    const videoButton = document.getElementById('video-button');
    let localStream = null;
    const peerConnections = new Map(); // Store all peer connections
    const participantView = document.getElementById('participant-view');
    let localUsername = '';

    let checkNewPeersInterval;

    joinButton.addEventListener('click', async () => {
        const username = document.getElementById('username').value.trim();
        if (username) {
            try {
                await joinSession(username);
                document.getElementById('join-screen').style.display = 'none';
                document.getElementById('control-panel').style.display = 'block';
                participantView.style.display = 'grid';  // Changed to grid
            } catch (error) {
                console.error('Error joining session:', error);
            }
        } else {
            alert('Please enter your name');
        }
    });

    muteButton.addEventListener('click', () => {
        if (localStream) {
            const audioTrack = localStream.getAudioTracks()[0];
            audioTrack.enabled = !audioTrack.enabled;
            muteButton.textContent = audioTrack.enabled ? 'Mute' : 'Unmute';
        }
    });

    videoButton.addEventListener('click', () => {
        if (localStream) {
            const videoTrack = localStream.getVideoTracks()[0];
            videoTrack.enabled = !videoTrack.enabled;
            videoButton.textContent = videoTrack.enabled ? 'Stop Video' : 'Start Video';
        }
    });

    async function createPeerConnection(targetUsername) {
        console.log(`Creating peer connection for ${targetUsername}`);
        const pc = new RTCPeerConnection({
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' }
            ]
        });

        // Add transceivers to ensure we can receive media
        pc.addTransceiver('video', {direction: 'sendrecv'});
        pc.addTransceiver('audio', {direction: 'sendrecv'});
          pc.ontrack = (event) => {            console.log(`Received track from ${targetUsername}:`, event.track.kind);
            
            // Always create a new MediaStream for the track
            const stream = new MediaStream([event.track]);
            console.log(`Created new stream for ${targetUsername} with ${event.track.kind} track`);
            
            const existingVideo = document.querySelector(`video[data-peer="${targetUsername}"]`);
            if (existingVideo) {
                // For existing video element, we need to add the track to its stream
                const existingStream = existingVideo.srcObject;
                existingStream.addTrack(event.track);
                console.log(`Added ${event.track.kind} track to existing stream for ${targetUsername}`);
            } else {
                console.log(`Creating new video element for ${targetUsername}`);
                const videoContainer = document.createElement('div');
                videoContainer.style.position = 'relative';
                
                const video = document.createElement('video');
                video.srcObject = stream;
                video.autoplay = true;
                video.playsInline = true;
                video.muted = targetUsername === 'local';  // Only mute local video
                video.setAttribute('data-peer', targetUsername);
                video.style.width = '300px';
                video.style.height = '225px';
                
                // Add play handler to debug video playback
                video.onplay = () => console.log(`Video started playing for ${targetUsername}`);
                video.onloadedmetadata = () => {
                    console.log(`Video metadata loaded for ${targetUsername}`);
                    video.play().catch(e => console.error(`Error playing video for ${targetUsername}:`, e));
                };
                
                videoContainer.appendChild(video);
                
                // Add user label
                const label = document.createElement('div');
                label.textContent = targetUsername;
                label.style.position = 'absolute';
                label.style.bottom = '8px';
                label.style.left = '8px';
                label.style.background = 'rgba(0, 0, 0, 0.6)';
                label.style.color = 'white';
                label.style.padding = '4px 8px';
                label.style.borderRadius = '4px';
                label.style.fontSize = '12px';
                videoContainer.appendChild(label);
                
                participantView.appendChild(videoContainer);
                console.log(`Added video element for ${targetUsername}`);
            }
            
            // Add the track to the stream
            stream.addTrack(event.track);
            console.log(`Added ${event.track.kind} track to stream for ${targetUsername}`);

            // Log all current video elements
            const videos = participantView.querySelectorAll('video');
            console.log(`Current video elements: ${videos.length}`);
            videos.forEach(v => console.log(` - ${v.getAttribute('data-peer')}`));
        };

        pc.onicecandidate = async (event) => {
            if (event.candidate) {
                try {
                    const candidate = {
                        sdpMid: event.candidate.sdpMid,
                        sdpMLineIndex: event.candidate.sdpMLineIndex,
                        candidate: event.candidate.candidate
                    };
                    
                    console.log('Sending ICE candidate:', candidate);
                    
                    const response = await fetch('/ice-candidate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            username: localUsername,
                            target: targetUsername,
                            candidate: candidate
                        })
                    });
                    
                    if (!response.ok) {
                        const error = await response.text();
                        throw new Error(`Failed to send ICE candidate: ${response.status} - ${error}`);
                    }
                } catch (error) {
                    console.error('Error sending ICE candidate:', error);
                }
            }
        };        pc.onconnectionstatechange = () => {
            console.log(`Connection state for ${targetUsername}: ${pc.connectionState}`);
            if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
                console.log(`Connection to ${targetUsername} ${pc.connectionState}`);
                removeParticipant(targetUsername);
            }
        };

        return pc;
    }

    function removeParticipant(username) {
        console.log(`Removing participant: ${username}`);
        const video = document.querySelector(`video[data-peer="${username}"]`);
        if (video) {
            video.srcObject = null;
            video.remove();
        }
        if (peerConnections.has(username)) {
            const pc = peerConnections.get(username);
            pc.close();
            peerConnections.delete(username);
        }

        // If this was the last peer, stop checking for new ones
        if (peerConnections.size === 0) {
            clearInterval(checkNewPeersInterval);
        }
    }

    async function joinSession(username) {
        try {
            localUsername = username;
            console.log(`Joining session as ${username}`);

            // Get user media first
            localStream = await navigator.mediaDevices.getUserMedia({ 
                audio: true, 
                video: true 
            });
            console.log('Got local media stream:', localStream.getTracks());

            // Add local video
            const localVideo = document.createElement('video');
            localVideo.srcObject = localStream;
            localVideo.autoplay = true;
            localVideo.playsInline = true;
            localVideo.classList.add('local-video');
            localVideo.setAttribute('data-peer', 'local');
            participantView.appendChild(localVideo);
            console.log('Added local video element');            // Create server connection
            const pc = await createPeerConnection('server');
            peerConnections.set('server', pc);

            // Add tracks to server connection
            if (localStream) {
                localStream.getTracks().forEach(track => {
                    pc.addTrack(track, localStream);
                    console.log(`Added ${track.kind} track to server connection`);
                });
            }

            // Wait a moment for tracks to be processed
            await new Promise(resolve => setTimeout(resolve, 1000));

            // Create and send offer
            const offer = await pc.createOffer({
                offerToReceiveAudio: true,
                offerToReceiveVideo: true
            });
            await pc.setLocalDescription(offer);
            console.log('Created initial offer:', offer);

            const response = await fetch('/offer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: username,
                    type: offer.type,
                    sdp: offer.sdp
                })
            });

            if (!response.ok) {
                throw new Error('Failed to send offer');
            }

            const data = await response.json();
            console.log('Received server response:', data);
            await pc.setRemoteDescription(new RTCSessionDescription({
                type: data.type,
                sdp: data.sdp
            }));

            // Connect with other peers
            if (data.otherPeers && data.otherPeers.length > 0) {
                console.log(`Connecting to other peers:`, data.otherPeers);
                for (const peer of data.otherPeers) {
                    await connectToPeer(peer);
                }
            }

            // Start checking for new peers periodically
            checkNewPeersInterval = setInterval(checkForNewPeers, 5000);
        } catch (error) {
            console.error('Error joining session:', error);
            throw error;
        }
    }    async function connectToPeer(targetUsername) {
        try {
            console.log(`Connecting to peer ${targetUsername}`);
            if (peerConnections.has(targetUsername)) {
                console.log(`Already connected to ${targetUsername}`);
                return;
            }

            const pc = await createPeerConnection(targetUsername);
            peerConnections.set(targetUsername, pc);            // Add local tracks to the connection
            if (localStream) {
                console.log(`Adding ${localStream.getTracks().length} tracks to connection with ${targetUsername}`);
                localStream.getTracks().forEach(track => {
                    pc.addTrack(track, localStream);
                    console.log(`Added ${track.kind} track to connection with ${targetUsername}`);
                });
            }

            // Wait a moment for tracks to be processed
            await new Promise(resolve => setTimeout(resolve, 1000));

            // Create and send offer
            const offer = await pc.createOffer();
            console.log(`Created offer for ${targetUsername}:`, offer);
            
            // Set local description first
            await pc.setLocalDescription(offer);

            const response = await fetch('/connect-peer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: localUsername,
                    target: targetUsername,
                    type: offer.type,
                    sdp: offer.sdp
                })
            });

            if (!response.ok) {
                throw new Error('Failed to connect to peer');
            }

            const data = await response.json();
            await pc.setRemoteDescription(new RTCSessionDescription({
                type: data.type,
                sdp: data.sdp
            }));

            console.log(`Successfully connected to ${targetUsername}`);
        } catch (error) {
            console.error(`Error connecting to peer ${targetUsername}:`, error);
            if (peerConnections.has(targetUsername)) {
                const pc = peerConnections.get(targetUsername);
                pc.close();
                peerConnections.delete(targetUsername);
            }
        }
    }

    async function checkForNewPeers() {
        try {
            const response = await fetch('/notify-new-peer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: localUsername })
            });

            if (!response.ok) {
                throw new Error('Failed to check for new peers');
            }

            const data = await response.json();
            const newPeers = data.peers.filter(peer => !peerConnections.has(peer));
            
            if (newPeers.length > 0) {
                console.log('Found new peers:', newPeers);
                for (const peer of newPeers) {
                    await connectToPeer(peer);
                }
            }
        } catch (error) {
            console.error('Error checking for new peers:', error);
        }
    }
});

