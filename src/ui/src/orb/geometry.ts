/** Screen/dock geometry helpers for the floating orb window. */

export type ScreenRect = { x: number; y: number; width: number; height: number };
export type Edge = "left" | "right" | "top" | "bottom";

export function clamp(
  x: number,
  y: number,
  screen: ScreenRect,
  ball: number,
  dockSliver: number,
  allowDock: boolean,
) {
  const sliver = allowDock ? dockSliver : ball;
  const minX = screen.x - (ball - sliver);
  const maxX = screen.x + screen.width - sliver;
  const minY = screen.y - (ball - sliver);
  const maxY = screen.y + screen.height - sliver;
  return { x: Math.max(minX, Math.min(x, maxX)), y: Math.max(minY, Math.min(y, maxY)) };
}

export function nearestEdge(x: number, y: number, screen: ScreenRect, ball: number): Edge {
  const cx = x + ball / 2;
  const cy = y + ball / 2;
  const dists = {
    left: cx - screen.x,
    right: screen.x + screen.width - cx,
    top: cy - screen.y,
    bottom: screen.y + screen.height - cy,
  };
  return (Object.entries(dists).sort((a, b) => a[1] - b[1])[0][0]) as Edge;
}

export function edgeIfNear(
  x: number,
  y: number,
  screen: ScreenRect,
  ball: number,
  snapPx: number,
): Edge | null {
  if (x <= screen.x + snapPx) return "left";
  if (x + ball >= screen.x + screen.width - snapPx) return "right";
  if (y <= screen.y + snapPx) return "top";
  if (y + ball >= screen.y + screen.height - snapPx) return "bottom";
  return null;
}

export function dockedPos(
  x: number,
  y: number,
  edge: string,
  screen: ScreenRect,
  ball: number,
  dockSliver: number,
) {
  let nx = x;
  let ny = y;
  if (edge === "left") nx = screen.x - (ball - dockSliver);
  else if (edge === "right") nx = screen.x + screen.width - dockSliver;
  else if (edge === "top") ny = screen.y - (ball - dockSliver);
  else ny = screen.y + screen.height - dockSliver;
  return clamp(nx, ny, screen, ball, dockSliver, true);
}

export function undockedPos(
  x: number,
  y: number,
  edge: string,
  screen: ScreenRect,
  ball: number,
  dockSliver: number,
  pad = 8,
) {
  let nx = x;
  let ny = y;
  if (edge === "left") nx = screen.x + pad;
  else if (edge === "right") nx = screen.x + screen.width - ball - pad;
  else if (edge === "top") ny = screen.y + pad;
  else ny = screen.y + screen.height - ball - pad;
  return clamp(nx, ny, screen, ball, dockSliver, false);
}
