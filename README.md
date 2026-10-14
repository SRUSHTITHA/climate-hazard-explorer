# Climate Hazard Explorer

Live Demo: [View Climate Hazard Explorer](https://climate-hazard-explorer-2mt04x0dx-sru7.vercel.app/)

Climate Hazard Explorer is a full-stack web application for analyzing historical heatwave patterns across geographic regions. It uses React for interactive visualizations, FastAPI for data processing and API endpoints, and MongoDB for caching analysis results.

## Features

- Geographic selection: Choose preset regions or define custom points and latitude–longitude bounding boxes.
- Historical analysis: Analyze heatwaves over a selected time period using daily maximum temperature data from Open-Meteo ERA5.
- Heatwave detection: Identify events using a percentile-based temperature threshold and a consecutive-day rule.
- Climate metrics: Explore annual frequency, duration, intensity, rolling averages, and historical event records.
- Trend analysis: View long-term trends and summary insights with appropriate uncertainty considerations.
- Data quality: Handle missing or invalid observations and report data availability.
- Export: Download annual metrics as CSV or print and save reports as PDF.

## Technology Stack

- Frontend: React, Vite, JavaScript
- Backend: Python, FastAPI
- Database: MongoDB
- Climate data: Open-Meteo ERA5
- Deployment: Vercel (frontend), Render (backend)

## How It Works

1. Select a geographic region and analysis period.
2. Retrieve historical daily maximum temperature data.
3. Validate and process observations, accounting for missing data.
4. Apply the heatwave detection criteria and calculate annual metrics.
5. Cache results in MongoDB and return analysis data through the API.
6. Display interactive visualizations and summary insights in the frontend.

## Heatwave Methodology

A heatwave is identified using a percentile-based temperature threshold and a minimum consecutive-day requirement. The analysis calculates event frequency, duration, intensity, and annual trends.

Results depend on the selected region, historical baseline, data availability, and detection parameters. Heatwave indicators describe meteorological conditions and should not be interpreted directly as measurements of human health impacts.

## Run Locally

### Prerequisites

- Node.js and npm
- Python compatible with `backend/requirements.txt`
- A MongoDB instance

### 1. Start the Backend

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment, then install dependencies:

```bash
pip install -r requirements.txt
```

Create `backend/.env` using `backend/.env.example` and configure your MongoDB connection.

Start the API:

```bash
uvicorn app.main:app --reload
```

The API documentation is available at `http://localhost:8000/docs`.

### 2. Start the Frontend

In a separate terminal:

```bash
cd frontend
npm install
```

Create `frontend/.env` using `frontend/.env.example` and set the backend URL:

```env
VITE_API_URL=http://localhost:8000
```

Start the development server:

```bash
npm run dev
```

### 3. Build for Production

```bash
npm run build
```

Run this command from the `frontend` directory.

## Configuration

Configure the following values through environment variables:

- `MONGODB_URI`: MongoDB connection string.
- `MONGODB_DB_NAME`: MongoDB database name.
- `CORS_ALLOWED_ORIGINS`: Comma-separated list of permitted frontend origins.
- `VITE_API_URL`: Backend base URL used by the frontend.

For deployment, configure environment variables in the relevant hosting dashboards. Do not commit database credentials or other secrets to GitHub.

## Limitations

- Results depend on the completeness and quality of historical observations.
- Missing observations must not be treated as non-heatwave days.
- Bounding-box analysis uses sampled grid cells rather than every location within the region.
- Trend estimates should be interpreted cautiously, particularly for short or autocorrelated time series.

## Project Structure

```text
frontend/
  src/                 # React UI, API client, visualizations
backend/
  app/
    api/               # API endpoints
    engine/            # Detection, metrics, and trend analysis
    services/          # Data ingestion, analysis, and storage
```
