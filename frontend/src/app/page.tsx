import ManhattanExplorer from "@/components/manhattan/ManhattanExplorer";

export const metadata = { title: "ResiliScore | Manhattan property explorer", description: "Explore Manhattan neighborhoods, buildings, terrain, and drainage in 3D, then assess a selected property." };

export default function Home() {
  return <ManhattanExplorer />;
}
