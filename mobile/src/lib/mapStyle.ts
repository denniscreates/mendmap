// Night-city map style (Google Maps on Android) matching the intro's navy look.
export const darkMapStyle = [
  { elementType: "geometry", stylers: [{ color: "#0e1834" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#8d9ab8" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#070d1f" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "poi.park", elementType: "geometry", stylers: [{ color: "#11301f" }, { visibility: "on" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#1c2b52" }] },
  { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#0a1228" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#28407a" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#050a18" }] },
];
