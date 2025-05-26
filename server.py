import asyncio
import logging
import json
import ssl
from pathlib import Path
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiohttp import web
import aiohttp_cors
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)

# Store active peer connections
peers = {}

async def index(request):
    content = open('templates/index.html', 'r').read()
    return web.Response(content_type='text/html', text=content)

async def cleanup_peer(username, app_peers_dict):
    """Clean up peer connection resources for a given username."""
    if username in app_peers_dict:
        logging.info(f"Attempting to clean up resources for user: {username}")
        peer_data = app_peers_dict.pop(username, None) # Atomically remove and get
        if peer_data:
            if peer_data.get('connection') and peer_data['connection'].signalingState != "closed":
                logging.info(f"Closing main connection for {username}")
                await peer_data['connection'].close()
            
            # Close all P2P connections this peer was involved in
            for target_peer_name, p2p_conn in peer_data.get('peer_connections', {}).items():
                if p2p_conn and p2p_conn.signalingState != "closed":
                    logging.info(f"Closing P2P connection between {username} and {target_peer_name}")
                    await p2p_conn.close()
                # Also remove the reverse reference from the target peer
                if target_peer_name in app_peers_dict and username in app_peers_dict[target_peer_name]['peer_connections']:
                    del app_peers_dict[target_peer_name]['peer_connections'][username]
            logging.info(f"Successfully cleaned up resources for user: {username}")
        else:
            logging.info(f"User {username} already cleaned up or not found during cleanup.")

async def handle_ice_candidate(request):
    """Handle incoming ICE candidate from a remote peer."""
    try:
        params = await request.json()
        username = params.get('username')
        target = params.get('target')
        candidate_payload = params.get('candidate') # This is the object from client: {sdpMid, sdpMLineIndex, candidate}
        
        logging.info(f"Received ICE candidate from {username} to {target}: {candidate}")
        logging.info(f"Current peers: {list(peers.keys())}")
        
        if target == 'server':
            if username in peers:
                pc = peers[username]['connection']
                logging.info(f"Using main connection for {username}")
            else:
                logging.warning(f"No main connection found for {username}")
                return web.Response(status=404, text=f"No connection found for {username}")
        else:
            if target in peers and username in peers[target]['peer_connections']:
                pc = peers[target]['peer_connections'][username]
                logging.info(f"Using peer connection {username}->{target}")
            else:
                if target not in peers:
                    logging.warning(f"Target peer {target} not found. Available peers: {list(peers.keys())}")
                else:
                    logging.warning(f"No peer connection found for {username} in {target}'s connections. Available connections: {list(peers[target]['peer_connections'].keys())}")
                return web.Response(status=404, text='Peer connection not found')

        try:
            candidate_string = candidate_payload.get('candidate')
            client_sdp_mid = candidate_payload.get('sdpMid')
            client_sdp_mline_index = candidate_payload.get('sdpMLineIndex')

            if not candidate_string:
                logging.error("ICE candidate string is missing from client payload.")
                return web.Response(status=400, text="ICE candidate string is missing")
            if client_sdp_mid is None:
                logging.error("sdpMid is missing from client payload for ICE candidate.")
                return web.Response(status=400, text="sdpMid is missing")
            if client_sdp_mline_index is None: # sdpMLineIndex can be 0
                logging.error("sdpMLineIndex is missing from client payload for ICE candidate.")
                return web.Response(status=400, text="sdpMLineIndex is missing")

            # For aiortc versions (likely < 1.0) where RTCIceCandidate.__init__
            # does not accept a 'candidate' keyword argument.
            # Use from_string() and then explicitly set sdpMid and sdpMLineIndex.
            ice_candidate_obj = RTCIceCandidate.from_string(candidate_string)
            
            # Ensure sdpMid and sdpMLineIndex from the client payload are used,
            # as these are directly from the browser's event.candidate object.
            ice_candidate_obj.sdpMid = client_sdp_mid
            ice_candidate_obj.sdpMLineIndex = client_sdp_mline_index

            # Defensive logging for the candidate string part
            log_candidate_str_part = ""
            if hasattr(ice_candidate_obj, 'candidate') and isinstance(ice_candidate_obj.candidate, str): # Modern aiortc
                log_candidate_str_part = ice_candidate_obj.candidate[:30]
            elif hasattr(ice_candidate_obj, 'to_string'): # Older aiortc
                try:
                    log_candidate_str_part = ice_candidate_obj.to_string()[:30]
                except Exception:
                    log_candidate_str_part = "[error getting string]"
            else: # Fallback to the raw string from client
                log_candidate_str_part = candidate_string[:30]

            logging.info(f"Adding ICE candidate for {target} (from {username}): sdpMid={ice_candidate_obj.sdpMid}, sdpMLineIndex={ice_candidate_obj.sdpMLineIndex}, candidate_str_part={log_candidate_str_part}...")
            await pc.addIceCandidate(ice_candidate_obj)
            return web.Response(status=200)
        except Exception as e: # More general catch for addIceCandidate issues
            logging.error(f"Error processing or adding ICE candidate: {str(e)}")
            return web.Response(status=400, text=f"Error processing or adding ICE candidate: {str(e)}")

    except Exception as e:
        logging.error(f"Error handling ICE candidate: {str(e)}")
        return web.Response(status=500, text=str(e))

async def connect_peer(request):
    """Connect to a remote peer."""
    try:
        params = await request.json()
        username = params.get('username')
        target = params.get('target')
        sdp = params.get('sdp')
        sdp_type = params.get('type')

        # Validate required parameters
        if not username:
            raise web.HTTPBadRequest(text='Username is required')
        if not target:
            raise web.HTTPBadRequest(text='Target is required')
        if not sdp:
            raise web.HTTPBadRequest(text='SDP is required')
        if not sdp_type:
            raise web.HTTPBadRequest(text='SDP type is required')

        if target not in peers:
            raise web.HTTPNotFound(text='Target peer not found')

        # Ensure the initiating user ('username') is already known (i.e., has called /offer)
        if username not in peers:
            logging.warning(f"Initiator user '{username}' for connect-peer not found. User must call /offer first.")
            raise web.HTTPNotFound(text=f"Initiating user '{username}' not found. Please establish a server connection first via /offer.")

        logging.info(f"Connecting peers: {username} -> {target}")

        # Create a new peer connection for the target
        pc = RTCPeerConnection()
        
        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logging.info(f"P2P ICE connection state between {username} and {target} is {pc.iceConnectionState}")
            if pc.iceConnectionState == "failed" or pc.iceConnectionState == "closed" or pc.iceConnectionState == "disconnected":
                logging.warning(f"P2P connection {username}<->{target} failed/closed/disconnected. Cleaning up {username}'s side.")
                await cleanup_peer_p2p_connection(username, target, pc) # Cleanup this specific P2P

        @pc.on("track")
        async def on_track(track):
            logging.info(f"Track received on connection {username}->{target}: {track.kind}")
            # This track is from 'target' and is being sent to 'username' over their P2P connection.
            # The server typically doesn't need to process this track in a simple P2P setup;
            # it's handled by 'username's client.
            # The previous logic incorrectly added this track to peers[username]['tracks'] (username's outgoing tracks).
            logging.info(f"P2P track ({track.kind}) received from {target} for {username} on their direct connection.")

        # Store the P2P connection.
        # It's crucial that peers[username] and peers[target] exist from their /offer calls.
        if username in peers and target in peers:
            peers[username]['peer_connections'][target] = pc
            peers[target]['peer_connections'][username] = pc # Bidirectional reference to the same pc object
        else:
            logging.error(f"Cannot establish P2P: {username} or {target} not found in peers dictionary.")
            await pc.close() # Clean up the newly created PC
            raise web.HTTPNotFound(text=f"Initiator {username} or target {target} not found.")

        # Set up the offer
        offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
        await pc.setRemoteDescription(offer)
        
        # Add existing tracks from the target peer to this connection
        if target in peers:
            for track in peers[target].get('tracks', []): # Ensure 'tracks' key exists
                pc.addTrack(track)
                logging.info(f"Added existing {track.kind} track from {target} to {username}'s new P2P connection with {target}")
        
        # Create and send answer
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        response_data = {
            'sdp': pc.localDescription.sdp,
            'type': pc.localDescription.type
        }
        
        return web.Response(
            content_type='application/json',
            text=json.dumps(response_data)
        )
    except Exception as e:
        logging.error(f"Error connecting peers: {str(e)}")
        raise web.HTTPInternalServerError(text=str(e))

async def cleanup_peer_p2p_connection(user_a, user_b, pc_to_close):
    """Cleans up a specific P2P connection between two users."""
    logging.info(f"Cleaning up P2P connection between {user_a} and {user_b}")
    if pc_to_close and pc_to_close.signalingState != "closed":
        await pc_to_close.close()

    if user_a in peers and user_b in peers[user_a].get('peer_connections', {}):
        del peers[user_a]['peer_connections'][user_b]
        logging.info(f"Removed P2P conn {user_a}->{user_b}")

    if user_b in peers and user_a in peers[user_b].get('peer_connections', {}):
        del peers[user_b]['peer_connections'][user_a]
        logging.info(f"Removed P2P conn {user_b}->{user_a}")

async def notify_new_peer(request):
    """Notify about new peer joining."""
    try:
        params = await request.json()
        username = params.get('username')
        if not username:
            raise web.HTTPBadRequest(text='Username is required')
        
        # Get list of all peers except the requesting one
        other_peers = [peer for peer in peers.keys() if peer != username]
        
        return web.Response(
            content_type='application/json',
            text=json.dumps({'peers': other_peers})
        )
    except Exception as e:
        logging.error(f"Error in notify_new_peer: {str(e)}")
        raise web.HTTPInternalServerError(text=str(e))

async def offer(request):
    """Handle offer from remote peer."""
    try:
        params = await request.json()
        username = params.get('username')
        sdp = params.get('sdp')
        sdp_type = params.get('type')

        # Validate required parameters
        if not username:
            raise web.HTTPBadRequest(text='Username is required')
        if not sdp:
            raise web.HTTPBadRequest(text='SDP is required')
        if not sdp_type:
            raise web.HTTPBadRequest(text='SDP type is required')

        logging.info(f"Received offer from {username}")

        # Create new peer connection for this user
        pc = RTCPeerConnection()

        # Initialize or update peer state
        if username not in peers:
            peers[username] = {
                'connection': pc,
                'peer_connections': {},
                'tracks': []
            }
        else:
            # User is re-offering. Close old main connection, update to new one.
            if peers[username].get('connection'):
                logging.info(f"User {username} is re-offering. Closing old main server connection.")
                await peers[username]['connection'].close()
            peers[username]['connection'] = pc
            # Decide on re-offer strategy:
            # Option A: Preserve P2P connections and tracks (current implicit behavior if not cleared)
            # Option B: Clear P2P connections and tracks, forcing re-establishment
            # For simplicity and to avoid breaking existing P2P, let's preserve them for now.
            # If Option B is desired:
            # for p2p_target, p2p_conn_obj in list(peers[username]['peer_connections'].items()): # list() for safe iteration
            #     await cleanup_peer_p2p_connection(username, p2p_target, p2p_conn_obj)
            # peers[username]['peer_connections'] = {}
            # peers[username]['tracks'] = []

            # To match original implicit behavior of clearing P2P on re-offer:
            # peers[username]['peer_connections'] = {}
            # peers[username]['tracks'] = [] # And reset tracks

        @pc.on("track")
        async def on_track(track):
            logging.info(f"Track {track.kind} received from {username} on main server connection.")
            # Store user's own track if not already present
            # This list (`peers[username]['tracks']`) holds tracks *sent by* this username to the server.
            if username in peers and track not in peers[username]['tracks']:
                peers[username]['tracks'].append(track)
                logging.info(f"Stored {track.kind} track from {username}.")
            elif username in peers and track in peers[username]['tracks']:
                logging.info(f"{track.kind} track from {username} already stored.")
            else:
                logging.warning(f"Could not store track from {username} as peer entry not fully initialized or track already present.")

            # Forward this track from 'username' to other peers 'username' is directly connected to
            if username in peers and 'peer_connections' in peers[username]:
                for target_peer_name, p2p_conn in peers[username]['peer_connections'].items():
                    if p2p_conn and p2p_conn.signalingState != "closed":
                        try:
                            logging.info(f"Attempting to forward {track.kind} track from {username} to {target_peer_name}.")
                            p2p_conn.addTrack(track)
                        except Exception as e: # Consider more specific exceptions like aiortc.InvalidStateError
                            logging.error(f"Error forwarding {track.kind} track from {username} to {target_peer_name}: {str(e)}")

        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logging.info(f"Main server connection ICE state for {username} is {pc.iceConnectionState}")
            if pc.iceConnectionState == "failed" or pc.iceConnectionState == "closed" or pc.iceConnectionState == "disconnected":
                logging.warning(f"Main server connection for {username} failed/closed. Cleaning up peer.")
                await cleanup_peer(username, peers) # Pass the global peers dict

        # Set up the offer
        offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
        await pc.setRemoteDescription(offer)
        
        # Create and send answer
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        # Get list of other connected peers
        other_peers = [peer for peer in peers.keys() if peer != username]
        
        return web.Response(
            content_type='application/json',
            text=json.dumps({
                'sdp': pc.localDescription.sdp,
                'type': pc.localDescription.type,
                'otherPeers': other_peers
            })
        )
    except Exception as e:
        logging.error(f"Error processing offer: {str(e)}")
        raise web.HTTPInternalServerError(text=str(e))

async def answer(request):
    """Handle answer from remote peer."""
    try:
        params = await request.json()
        username = params.get('username')
        target = params.get('target')
        
        if not all([username, target]):
            raise web.HTTPBadRequest(text='Username and target are required')
            
        if target not in peers:
            raise web.HTTPNotFound(text='Target peer not found')
            
        peer_data = peers[target]
        if username in peer_data['peer_connections']:
            pc = peer_data['peer_connections'][username]
            answer = RTCSessionDescription(sdp=params['sdp'], type=params['type'])
            await pc.setRemoteDescription(answer)
            return web.Response(status=200)
            
        return web.HTTPNotFound(text='Connection not found')
    except Exception as e:
        logging.error(f"Error processing answer: {str(e)}")
        raise web.HTTPInternalServerError(text=str(e))

def init_app():
    """Create and configure the application."""
    app = web.Application()
    
    # Configure CORS with proper options
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers=["Content-Type", "X-Requested-With", "Authorization"],
            allow_methods=["GET", "POST", "OPTIONS"]
        )
    })    # Create routes with CORS support
    routes = [
        web.get('/', index),
        web.post('/offer', offer),
        web.post('/answer', answer),
        web.post('/ice-candidate', handle_ice_candidate),
        web.post('/connect-peer', connect_peer),
        web.post('/notify-new-peer', notify_new_peer)
    ]
    
    # Add routes and enable CORS
    for route in routes:
        app.router.add_route(route.method, route.path, route.handler)
        cors.add(app.router.add_resource(route.path))
    
    # Add static route for serving CSS and JavaScript files
    # Use absolute path to avoid any path resolution issues
    static_path = str(Path(__file__).parent / 'static')
    app.router.add_static('/static/', static_path)

    # Apply CORS to all routes
    for route in list(app.router.routes()):
        cors.add(route)

    # Pass the peers dictionary to cleanup tasks if needed, e.g., on shutdown
    # async def on_shutdown(app_instance):
    #    for peer_name in list(peers.keys()): # list() for safe iteration
    #        await cleanup_peer(peer_name, peers)
    # app.on_shutdown.append(on_shutdown)
    return app

# Run the application
if __name__ == '__main__':
    app = init_app()
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain('ssl/cert.pem', 'ssl/key.pem')
    web.run_app(app, host='0.0.0.0', port=8443, ssl_context=ssl_context)
