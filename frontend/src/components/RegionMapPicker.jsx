import { useMemo, useState } from 'react';
import { MapContainer, TileLayer, Marker, Rectangle, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

const markerIcon = new L.Icon({
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41],
});

function ClickHandler({ mode, onPoint, onBoxClick }) {
  useMapEvents({ click(event) {
    const { lat, lng } = event.latlng;
    if (mode === 'point') onPoint({ lat: Number(lat.toFixed(5)), lon: Number(lng.toFixed(5)) });
    if (mode === 'box') onBoxClick({ lat: Number(lat.toFixed(5)), lon: Number(lng.toFixed(5)) });
  } });
  return null;
}

export default function RegionMapPicker({ mode = 'point', onApply, onClose }) {
  const [point, setPoint] = useState(null);
  const [firstCorner, setFirstCorner] = useState(null);
  const [box, setBox] = useState(null);
  const center = useMemo(() => [20.5937, 78.9629], []);
  const boxClick = (corner) => {
    if (!firstCorner) { setFirstCorner(corner); setBox(null); return; }
    const next = {
      south: Math.min(firstCorner.lat, corner.lat), north: Math.max(firstCorner.lat, corner.lat),
      west: Math.min(firstCorner.lon, corner.lon), east: Math.max(firstCorner.lon, corner.lon),
    };
    if (next.north - next.south < 0.01 || next.east - next.west < 0.01) {
      setFirstCorner(corner); setBox(null); return;
    }
    setBox(next); setFirstCorner(null);
  };
  const validBox = box && box.north > box.south && box.east > box.west
    && box.north - box.south <= 0.75 && box.east - box.west <= 0.75;
  return (
    <div className="map-picker" role="dialog" aria-label="Select region on map">
      <div className="map-picker-heading">
        <div><strong>Select a region on the map</strong><p>{mode === 'box' ? 'Click two corners to define a bounding box.' : 'Click the map to choose a point.'}</p></div>
        <button type="button" className="button-secondary" onClick={onClose}>Close</button>
      </div>
      <MapContainer center={center} zoom={4} scrollWheelZoom className="region-map">
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <ClickHandler mode={mode} onPoint={(value) => { setPoint(value); setBox(null); }} onBoxClick={boxClick} />
        {point ? <Marker position={[point.lat, point.lon]} icon={markerIcon} /> : null}
        {validBox ? <Rectangle bounds={[[box.south, box.west], [box.north, box.east]]} pathOptions={{ color: '#0d9488', weight: 2 }} /> : null}
        {firstCorner ? <Marker position={[firstCorner.lat, firstCorner.lon]} icon={markerIcon} /> : null}
      </MapContainer>
      <div className="map-picker-footer">
        <p className="subtitle">{mode === 'box' ? (validBox ? `S ${box.south}, W ${box.west}, N ${box.north}, E ${box.east}` : firstCorner ? 'First corner selected. Click the opposite corner.' : 'No box selected yet.') : point ? `Latitude ${point.lat} · Longitude ${point.lon}` : 'No point selected yet.'}</p>
        <button type="button" disabled={mode === 'point' ? !point : !validBox} onClick={() => { onApply(mode === 'point' ? point : box); onClose(); }}>Use this region</button>
      </div>
      <p className="subtitle">Map tiles are provided by OpenStreetMap. Point and box selections use your existing analysis API parameters.</p>
    </div>
  );
}
