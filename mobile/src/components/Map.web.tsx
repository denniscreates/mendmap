import Ionicons from "@expo/vector-icons/Ionicons";
import { Component, type ReactNode } from "react";
import { StyleSheet, Text, View, type StyleProp, type ViewStyle } from "react-native";

/**
 * Web stand-in for react-native-maps, which only runs on phones. The page still works in a browser
 * (sign in, lists, chat, bookings); where a map would be, it says the map is in the phone app.
 */
export type Region = { latitude: number; longitude: number; latitudeDelta: number; longitudeDelta: number };

type Props = { style?: StyleProp<ViewStyle>; children?: ReactNode; [key: string]: unknown };

export default class MapView extends Component<Props> {
  // The screens move the map with these; on the web there is nothing to move.
  animateToRegion() {}
  animateCamera() {}
  fitToCoordinates() {}

  render() {
    return (
      <View style={[this.props.style, styles.box]}>
        <Ionicons name="map-outline" size={34} color="#8d9ab8" />
        <Text style={styles.text}>The map is in the MendMap phone app.</Text>
      </View>
    );
  }
}

export const Marker = (_: Record<string, unknown>) => null;
export const Polyline = (_: Record<string, unknown>) => null;

const styles = StyleSheet.create({
  box: { alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "#0e1834", minHeight: 160 },
  text: { color: "#8d9ab8", fontSize: 14 },
});
