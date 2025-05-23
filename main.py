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

async def cleanup_peer(username):
    """Clean up peer connection resources for a given username."""
    if username in peers:
        peer_data = peers[username]
        await peer_data['connection'].close()
        for peer_conn in peer_data['peer_connections'].values():
            await peer_conn.close()
        del peers[username]
        logging.info(f"Cleaned up connection for user: {username}")

async def handle_ice_candidate(request):
    """Handle incoming ICE candidate from a remote peer."""
    try:
        params = await request.json()
        username = params.get('username')
        target = params.get('target')
        candidate = params.get('candidate')
        
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
            # Parse ICE candidate string to extract components
            candidate_str = candidate.get('candidate')
            sdp_mid = candidate.get('sdpMid')
            sdp_mline_index = candidate.get('sdpMLineIndex')

            # Extract foundation
            foundation_match = candidate_str.split(' ')[0]
            foundation = foundation_match.split(':')[1]

            # Extract other components
            parts = candidate_str.split(' ')
            component = int(parts[1])
            protocol = parts[2].lower()
            priority = int(parts[3])
            ip = parts[4]
            port = int(parts[5])
            type_idx = parts.index('typ') + 1
            type = parts[type_idx]

            logging.info(f"Creating ICE candidate with: foundation={foundation}, component={component}, "
                        f"protocol={protocol}, priority={priority}, ip={ip}, port={port}, type={type}")

            # Create the RTCIceCandidate with required parameters
            ice_candidate = RTCIceCandidate(
                foundation=foundation,
                component=component,
                protocol=protocol,
                priority=priority,
                ip=ip,
                port=port,
                type=type,
                sdpMid=sdp_mid,
                sdpMLineIndex=sdp_mline_index
            )

            await pc.addIceCandidate(ice_candidate)
            return web.Response(status=200)

        except (IndexError, ValueError) as e:
            logging.error(f"Error parsing ICE candidate: {str(e)}")
            return web.Response(status=400, text=f"Invalid ICE candidate format: {str(e)}")

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
        
        @pc.on("track")
        async def on_track(track):
            logging.info(f"Track received on connection {username}->{target}: {track.kind}")
            # This track is from 'target' and is being sent to 'username' over their P2P connection.
            # The server typically doesn't need to process this track in a simple P2P setup;
            # it's handled by 'username's client.
            # The previous logic incorrectly added this track to peers[username]['tracks'] (username's outgoing tracks).
            logging.info(f"P2P track ({track.kind}) received from {target} for {username} on their direct connection.")

        # Store the connections bidirectionally
        # Assumes peers[username] and peers[target] are correctly initialized by /offer
        peers[target]['peer_connections'][username] = pc
        peers[username]['peer_connections'][target] = pc

        # Set up the offer
        offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
        await pc.setRemoteDescription(offer)
        
        # Add existing tracks from the target peer to this connection
        if target in peers:
            for track in peers[target]['tracks']:
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
            # Keep existing peer_connections and tracks unless specific logic dictates otherwise.
            if peers[username].get('connection'):
                await peers[username]['connection'].close()
            peers[username]['connection'] = pc
            # If re-offer should clear P2P connections or tracks, add that logic here.
            # For now, we preserve them. Original code would clear peers[username]['peer_connections'].
            # To match original implicit behavior of clearing P2P on re-offer:
            # peers[username]['peer_connections'] = {}
            # peers[username]['tracks'] = [] # And reset tracks

        @pc.on("track")
        async def on_track(track):
            logging.info(f"Track {track.kind} received from {username} on main server connection.")
            # Store user's own track in their canonical track list
            if username in peers and track not in peers[username]['tracks']:
                peers[username]['tracks'].append(track)
                logging.info(f"Stored {track.kind} track from {username}.")

            # Forward this track from 'username' to other peers 'username' is directly connected to
            if username in peers and 'peer_connections' in peers[username]:
                for target_peer_name, p2p_conn in peers[username]['peer_connections'].items():
                    if p2p_conn and p2p_conn.signalingState != "closed":
                        try:
                            logging.info(f"Attempting to forward {track.kind} track from {username} to {target_peer_name}.")
                            p2p_conn.addTrack(track)
                        except Exception as e: # Consider more specific exceptions like aiortc.InvalidStateError
                            logging.error(f"Error forwarding {track.kind} track from {username} to {target_peer_name}: {str(e)}")

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

    return app

# Run the application
if __name__ == '__main__':
    app = init_app()
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain('ssl/cert.pem', 'ssl/key.pem')
    web.run_app(app, host='0.0.0.0', port=8443, ssl_context=ssl_context)
