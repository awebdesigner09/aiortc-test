# WebRTC Video Chat (aiortc-test)

A web application demonstrating a multi-party video chat session using WebRTC. This project likely utilizes the `aiortc` Python library for the backend to handle WebRTC signaling and media processing, and a vanilla HTML, CSS, and JavaScript frontend for the user interface.

## Features

*   **Join Session:** Users can join a video chat session by providing a username.
*   **Video/Audio Streaming:** Real-time video and audio communication between participants.
*   **Mute/Unmute Audio:** Users can mute or unmute their microphone during the session.
*   **Start/Stop Video:** Users can turn their camera on or off.
*   **Dynamic Participant View:** Video streams of participants are dynamically added to the interface.

## Tech Stack

### Frontend
*   **HTML5:** Structure of the web page (`templates/index.html`).
*   **CSS3:** Styling for the application (via `static/css/style.css`).
*   **JavaScript:** Client-side logic for WebRTC connections, DOM manipulation, and user interactions (via `static/js/main.js`).

### Backend (Assumed)
*   **Python 3.x**
*   **aiortc:** For handling WebRTC server-side logic, including signaling and media streams.
*   **ASGI Framework:** Such as `aiohttp`, `FastAPI`, or `Starlette` to serve the HTML/static files and handle WebSocket connections for signaling.
*   **WebSockets:** For real-time signaling between the clients and the server.

## Project Structure

Based on the `index.html` file, the project likely follows a structure similar to this:

```
aiortc-test/
├── templates/
│   └── index.html       # Main HTML page for the video chat interface
├── static/
│   ├── css/
│   │   └── style.css    # Stylesheets for the application
│   └── js/
│       └── main.js      # Client-side JavaScript for WebRTC and UI logic
├── server.py            # (Assumed) Python backend server (e.g., using aiohttp and aiortc)
├── requirements.txt     # (Assumed) Python dependencies
└── README.md            # This file
```

## Setup and Installation (Assumed Backend)

The following steps assume a Python backend using `aiortc` and an ASGI server like `uvicorn`.

1.  **Clone the repository (if applicable):**
    ```bash
    git clone <your-repository-url>
    cd aiortc-test
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python -m venv venv
    # On Windows
    venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3.  **Install Python dependencies:**
    If a `requirements.txt` file exists:
    ```bash
    pip install -r requirements.txt
    ```
    Otherwise, you might need to install `aiortc` and an ASGI server manually:
    ```bash
    pip install aiortc aiohttp uvicorn # or fastapi instead of aiohttp
    ```

4.  **Run the server:**
    This command depends on how your Python server (`server.py`) is structured. If it defines an ASGI application instance named `app`:
    ```bash
    uvicorn server:app --reload --host 0.0.0.0 --port 8080
    ```
    *(Adjust the host, port, and application variable name as needed.)*

## Usage

1.  **Start the backend server** as described in the "Setup and Installation" section.
2.  **Open your web browser** (Chrome or Firefox are recommended for good WebRTC support).
3.  **Navigate to the application URL** (e.g., `http://localhost:8080` or the IP/port your server is running on).
4.  You will see the **"Join the Session"** screen.
    *   Enter your desired username in the input field.
    *   Click the "Join" button.
5.  Your browser will likely **request permission** to access your camera and microphone. Grant these permissions to proceed.
6.  Once joined, your video should appear, and you'll be in the **control panel and participant view**.
    *   The `control-panel` allows you to:
        *   **Mute/Unmute** your audio using the "Mute" button.
        *   **Stop/Start** your video using the "Stop Video" button.
    *   The `participant-view` will display video elements for all connected participants.

## How It Works (Client-Side Overview)

*   **`index.html`**: Provides the basic UI structure with placeholders for user input, controls, and video displays.
*   **`static/css/style.css`**: Contains the visual styling for the application. (Currently, this file would need to be created and populated with styles).
*   **`static/js/main.js`**: This script is responsible for:
    *   Handling user input from the "Join" screen.
    *   Requesting access to the user's camera and microphone (getUserMedia API).
    *   Establishing a WebRTC connection (`RTCPeerConnection`):
        *   Connecting to a signaling server (likely via WebSockets, managed by the Python backend) to exchange session metadata (SDP offers/answers) and network information (ICE candidates) with other peers.
    *   Dynamically creating and managing `<video>` elements in the `participant-view` div to display local and remote video streams.
    *   Implementing the logic for the "Mute" and "Stop Video" buttons by manipulating local media tracks.

## Development Notes

*   The actual WebRTC logic, signaling, and dynamic DOM manipulation would be implemented in `static/js/main.js`.
*   The `static/css/style.css` file would need to be created to style the application beyond default browser styles.
*   The backend server (`server.py` or similar) is crucial for managing user sessions, signaling between clients, and potentially relaying media if direct P2P connections are not possible. `aiortc` provides the tools to build this server-side WebRTC functionality in Python.

---

This README provides a general outline. You'll want to fill in more specific details about your backend implementation, any specific libraries used beyond the assumed ones, and more detailed setup instructions once the backend is fully developed.