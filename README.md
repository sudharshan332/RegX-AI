# Regression Dashboard

This project consists of a React frontend and a Flask backend for displaying regression test results.

**Documentation:** For full project documentation, architecture diagrams, improvement suggestions, and AI integration roadmap, see [PROJECT_DOCUMENTATION_AND_ARCHITECTURE.md](PROJECT_DOCUMENTATION_AND_ARCHITECTURE.md).

## Prerequisites

- Node.js and npm (for React frontend)
- Python 3.x (for Flask backend)

## Setup

### 1. Install Frontend Dependencies

```bash
npm install
```

### 2. Install Backend Dependencies

```bash
pip install -r requirements.txt
```

Or if you need to use pip3:

```bash
pip3 install -r requirements.txt
```

### 3. Set Environment Variables (Optional)

**One place for API URL:** The frontend reads the API base URL from `REACT_APP_API_URL`. All pages use it via `src/config.js`—change it once to reflect your backend.

For **server deployment** (e.g. Rocky Linux at 10.111.52.90), create a `.env` in the project root (or set before build):

```bash
# Frontend: backend URL (no trailing slash). Used everywhere via src/config.js.
REACT_APP_API_URL=http://10.111.52.90:5001

# Backend: bind to all interfaces and port (for remote access)
export FLASK_HOST=0.0.0.0
export FLASK_PORT=5001
export FLASK_DEBUG=false
```

Then run `npm run build` so the built app uses that URL. On the server, start the backend with these env vars set so it listens on `0.0.0.0:5001`. Open the app at `http://10.111.52.90:3000` (dev server) or the URL where you serve the `build/` folder. Ensure firewall allows ports 5001 and 3000 (or 80 if using nginx).

For Triage Genie features, set the authentication token:

```bash
export TRIAGE_GENIE_TOKEN="your_triage_genie_token_here"
```

Or add it to your shell profile (`.bashrc`, `.zshrc`, etc.) for persistence.

## Running the Application

### Start the Flask Backend

In one terminal, navigate to the project root and run:

```bash
python3 backend/test_flask.py
```

Or use the provided script:

```bash
./start_backend.sh
```

The Flask server will start on **port 5001** (http://localhost:5001).

**Note:** If you're using Triage Genie features, make sure `TRIAGE_GENIE_TOKEN` is set, otherwise you'll get authentication errors.

### Start the React Frontend

In another terminal, navigate to the project root and run:

```bash
npm start
```

The React app will start on **port 3000** (http://localhost:3000) and will automatically open in your browser.

**Important:** Make sure the Flask backend is running before accessing the frontend, otherwise you'll see a connection error.

## Available Scripts

In the project directory, you can run:

### `npm start`

Runs the app in the development mode.\
Open [http://localhost:3000](http://localhost:3000) to view it in your browser.

The page will reload when you make changes.\
You may also see any lint errors in the console.

### `npm test`

Launches the test runner in the interactive watch mode.\
See the section about [running tests](https://facebook.github.io/create-react-app/docs/running-tests) for more information.

### `npm run build`

Builds the app for production to the `build` folder.\
It correctly bundles React in production mode and optimizes the build for the best performance.

The build is minified and the filenames include the hashes.\
Your app is ready to be deployed!

See the section about [deployment](https://facebook.github.io/create-react-app/docs/deployment) for more information.

### `npm run eject`

**Note: this is a one-way operation. Once you `eject`, you can't go back!**

If you aren't satisfied with the build tool and configuration choices, you can `eject` at any time. This command will remove the single build dependency from your project.

Instead, it will copy all the configuration files and the transitive dependencies (webpack, Babel, ESLint, etc) right into your project so you have full control over them. All of the commands except `eject` will still work, but they will point to the copied scripts so you can tweak them. At this point you're on your own.

You don't have to ever use `eject`. The curated feature set is suitable for small and middle deployments, and you shouldn't feel obligated to use this feature. However we understand that this tool wouldn't be useful if you couldn't customize it when you are ready for it.

## Learn More

You can learn more in the [Create React App documentation](https://facebook.github.io/create-react-app/docs/getting-started).

To learn React, check out the [React documentation](https://reactjs.org/).

### Code Splitting

This section has moved here: [https://facebook.github.io/create-react-app/docs/code-splitting](https://facebook.github.io/create-react-app/docs/code-splitting)

### Analyzing the Bundle Size

This section has moved here: [https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size](https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size)

### Making a Progressive Web App

This section has moved here: [https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app](https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app)

### Advanced Configuration

This section has moved here: [https://facebook.github.io/create-react-app/docs/advanced-configuration](https://facebook.github.io/create-react-app/docs/advanced-configuration)

### Deployment

This section has moved here: [https://facebook.github.io/create-react-app/docs/deployment](https://facebook.github.io/create-react-app/docs/deployment)

### `npm run build` fails to minify

This section has moved here: [https://facebook.github.io/create-react-app/docs/troubleshooting#npm-run-build-fails-to-minify](https://facebook.github.io/create-react-app/docs/troubleshooting#npm-run-build-fails-to-minify)
