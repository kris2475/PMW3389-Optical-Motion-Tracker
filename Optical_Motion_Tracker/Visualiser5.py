from collections import deque
import datetime
import math
import re
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import pygame
import serial
import serial.tools.list_ports


def select_port():
  ports = serial.tools.list_ports.comports()
  port_list = [f"{port.device} - {port.description}" for port in ports]
  device_mapping = {
      f"{port.device} - {port.description}": port.device for port in ports
  }

  if not port_list:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "No Ports Found", "No serial ports detected! Check USB connection."
    )
    sys.exit(1)

  selected_port = None
  root = tk.Tk()
  root.title("Select ESP32 Port")
  root.geometry("350x160")
  root.resizable(False, False)
  root.eval("tk::PlaceWindow . center")

  tk.Label(root, text="Select ESP32 Serial Port:", font=("Arial", 10, "bold")).pack(
      pady=12
  )
  combo = ttk.Combobox(root, values=port_list, state="readonly", width=40)
  combo.current(0)
  combo.pack(pady=5)

  def on_connect():
    nonlocal selected_port
    selection = combo.get()
    if selection:
      selected_port = device_mapping[selection]
      root.destroy()

  btn = tk.Button(
      root,
      text="Connect & Start",
      command=on_connect,
      bg="#007ACC",
      fg="white",
      font=("Arial", 9, "bold"),
      width=18,
      height=1,
  )
  btn.pack(pady=12)
  root.mainloop()
  return selected_port


CHOSEN_PORT = select_port()
if not CHOSEN_PORT:
  sys.exit(0)

BAUD_RATE = 115200

try:
  ser = serial.Serial(CHOSEN_PORT, BAUD_RATE, timeout=0.01)
  print(f"Successfully connected to {CHOSEN_PORT}")
except Exception as e:
  print(f"Error opening serial port {CHOSEN_PORT}: {e}")
  sys.exit(1)

pygame.init()
WIDTH, HEIGHT = 1200, 800
CANVAS_WIDTH = 900
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption(f"PMW3389 Tracking Dashboard [{CHOSEN_PORT}]")
clock = pygame.time.Clock()

font = pygame.font.SysFont("Arial", 18)
font_bold = pygame.font.SysFont("Arial", 20, bold=True)
font_small = pygame.font.SysFont("Arial", 15)

# Tracking states
dot_x = CANVAS_WIDTH // 2
dot_y = HEIGHT // 2
trail = []  # Stores tuples of (x, y, color)
scale = 1.0

# Telemetry states
current_squal = 0
last_dx = 0
last_dy = 0
abs_x = 0
abs_y = 0

# SQUAL History Buffer (stores last 120 points for sparkline)
squal_history = deque([0] * 120, maxlen=120)

# Performance metrics states
dpi = 1600
total_distance_cm = 0.0
current_speed_ips = 0.0
max_speed_ips = 0.0

# Domain Conversion / Heading States
current_angle_deg = 0.0
cardinal_dir = "None"

# Recording states
is_recording = False
recorded_session_data = []

# Notification state
save_notification = ""
notification_time = 0


def get_squal_color(squal):
  # Clamp SQUAL between 0 and 100 for smooth color interpolation
  squal = max(0, min(squal, 100))

  # Define color stops: (squal_threshold, (R, G, B))
  stops = [
      (0, (255, 0, 0)),  # Deep Red
      (25, (255, 110, 0)),  # Orange-Red
      (50, (255, 200, 0)),  # Amber / Yellow-Orange
      (75, (140, 230, 0)),  # Yellow-Green
      (100, (0, 255, 0)),  # Vibrant Green
  ]

  for i in range(len(stops) - 1):
    s1, c1 = stops[i]
    s2, c2 = stops[i + 1]
    if s1 <= squal <= s2:
      factor = (squal - s1) / (s2 - s1)
      r = int(c1[0] + factor * (c2[0] - c1[0]))
      g = int(c1[1] + factor * (c2[1] - c1[1]))
      b = int(c1[2] + factor * (c2[2] - c1[2]))
      return (r, g, b)
  return stops[-1][1]


def get_squal_label(squal):
  if squal > 80:
    return "Excellent"
  elif squal > 60:
    return "Good"
  elif squal > 40:
    return "Fair"
  elif squal > 20:
    return "Marginal"
  else:
    return "Poor Surface"


def toggle_recording():
  global is_recording, recorded_session_data, save_notification, notification_time
  if not is_recording:
    is_recording = True
    recorded_session_data = []
    save_notification = "Recording Started..."
    notification_time = pygame.time.get_ticks()
  else:
    is_recording = False
    root_prompt = tk.Tk()
    root_prompt.withdraw()
    default_name = (
        f"session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    user_filename = simpledialog.askstring(
        "Save Recording",
        "Enter filename for session export:",
        initialvalue=default_name,
    )
    root_prompt.destroy()

    if user_filename:
      if not user_filename.endswith(".txt"):
        user_filename += ".txt"
      try:
        with open(user_filename, "w") as f:
          f.write("=== PMW3389 RECORDED SESSION REPORT ===\n")
          f.write(
              f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
          )
          f.write(f"Config DPI: {dpi}\n")
          f.write(f"Total Distance Traveled: {total_distance_cm:.2f} cm\n")
          f.write(f"Peak Speed: {max_speed_ips:.1f} IPS\n")
          f.write(f"Final Absolute Position: X={abs_x}, Y={abs_y}\n")
          f.write(f"Final SQUAL: {current_squal}\n")
          f.write(f"Total Recorded Frames/Events: {len(recorded_session_data)}\n\n")
          f.write(
              "--- Event Log (dx, dy, squal, abs_x, abs_y, angle, speed) ---\n"
          )
          for entry in recorded_session_data:
            f.write(f"{entry}\n")
        save_notification = f"Saved: {user_filename}"
        notification_time = pygame.time.get_ticks()
      except Exception as e:
        print("Error saving recording file:", e)
        save_notification = "Error saving file!"
        notification_time = pygame.time.get_ticks()
    else:
      save_notification = "Recording discarded."
      notification_time = pygame.time.get_ticks()


def handle_save_screenshot():
  global save_notification, notification_time
  timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
  filename = f"pmw3389_screenshot_{timestamp}.png"
  try:
    pygame.image.save(screen, filename)
    save_notification = f"Screenshot Saved: {filename}"
    notification_time = pygame.time.get_ticks()
  except Exception as e:
    print("Error saving screenshot:", e)


def handle_clear_stats():
  global total_distance_cm, max_speed_ips, save_notification, notification_time
  trail.clear()
  total_distance_cm = 0.0
  max_speed_ips = 0.0
  squal_history.clear()
  squal_history.extend([0] * 120)
  save_notification = "Stats & Trail Cleared"
  notification_time = pygame.time.get_ticks()


running = True
while running:
  current_speed_ips = 0.0

  panel_x = CANVAS_WIDTH + 20
  btn_record_rect = pygame.Rect(panel_x, 690, 240, 32)
  btn_screenshot_rect = pygame.Rect(panel_x, 730, 240, 32)
  btn_clear_rect = pygame.Rect(panel_x, 770, 240, 32)

  for event in pygame.event.get():
    if event.type == pygame.QUIT:
      running = False
    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
      mouse_pos = event.pos
      if btn_record_rect.collidepoint(mouse_pos):
        toggle_recording()
      elif btn_screenshot_rect.collidepoint(mouse_pos):
        handle_save_screenshot()
      elif btn_clear_rect.collidepoint(mouse_pos):
        handle_clear_stats()
    elif event.type == pygame.KEYDOWN:
      if event.key == pygame.K_c:
        handle_clear_stats()
      elif event.key == pygame.K_r:
        toggle_recording()
      elif event.key == pygame.K_p:
        handle_save_screenshot()

  while ser.in_waiting > 0:
    line = ser.readline().decode("utf-8", errors="ignore").strip()

    if line.startswith("MOVE:"):
      match = re.search(
          r"dx=(-?\d+),dy=(-?\d+),squal=(\d+),x=(-?\d+),y=(-?\d+)", line
      )
      if match:
        last_dx = int(match.group(1))
        last_dy = int(match.group(2))
        current_squal = int(match.group(3))
        abs_x = int(match.group(4))
        abs_y = int(match.group(5))

        squal_history.append(current_squal)

        dot_x += int(last_dx * scale)
        dot_y += int(last_dy * scale)

        dot_x = max(10, min(CANVAS_WIDTH - 10, dot_x))
        dot_y = max(10, min(HEIGHT - 10, dot_y))

        squal_color = get_squal_color(current_squal)
        trail.append((dot_x, dot_y, squal_color))
        if len(trail) > 150:
          trail.pop(0)

        distance_counts = (last_dx**2 + last_dy**2) ** 0.5
        total_distance_cm += (distance_counts / dpi) * 2.54
        current_speed_ips = (distance_counts / dpi) * 60
        if current_speed_ips > max_speed_ips:
          max_speed_ips = current_speed_ips

        # Polar Heading Conversion
        if distance_counts > 0.2:
          math_angle = math.degrees(math.atan2(-last_dy, last_dx)) % 360
          current_angle_deg = math_angle
          directions = [
              "East",
              "North-East",
              "North",
              "North-West",
              "West",
              "South-West",
              "South",
              "South-East",
          ]
          sector = int((math_angle + 22.5) / 45) % 8
          cardinal_dir = directions[sector]

        if is_recording:
          recorded_session_data.append(
              f"dx={last_dx}, dy={last_dy}, squal={current_squal},"
              f" x={abs_x}, y={abs_y}, angle={current_angle_deg:.1f},"
              f" speed={current_speed_ips:.1f}"
          )

    elif line.startswith("STATUS:"):
      match = re.search(r"squal=(\d+)", line)
      if match:
        current_squal = int(match.group(1))
        squal_history.append(current_squal)

  # --- RENDER DASHBOARD & CANVAS ---
  screen.fill((20, 20, 20))

  # Left Canvas Area
  pygame.draw.rect(screen, (30, 30, 30), (0, 0, CANVAS_WIDTH, HEIGHT))
  pygame.draw.line(
      screen, (70, 70, 70), (CANVAS_WIDTH, 0), (CANVAS_WIDTH, HEIGHT), 2
  )

  # Draw multi-colored smooth gradient trail segments
  if len(trail) > 1:
    for i in range(len(trail) - 1):
      pt1 = (trail[i][0], trail[i][1])
      pt2 = (trail[i + 1][0], trail[i + 1][1])
      seg_color = trail[i + 1][2]
      pygame.draw.line(screen, seg_color, pt1, pt2, 2)

  # Draw actual cursor with current gradient color
  squal_color = get_squal_color(current_squal)
  pygame.draw.circle(screen, squal_color, (dot_x, dot_y), 8)

  # Right Telemetry Panel
  panel_x = CANVAS_WIDTH + 20

  # 1. Sensor Telemetry Section
  screen.blit(
      font_bold.render("Sensor Telemetry", True, (255, 255, 255)), (panel_x, 15)
  )

  screen.blit(
      font_bold.render(f"SQUAL: {current_squal}", True, squal_color),
      (panel_x, 42),
  )

  q_label = get_squal_label(current_squal)
  screen.blit(
      font.render(f"Quality: {q_label}", True, (180, 180, 180)), (panel_x, 65)
  )

  bar_w, bar_h, bar_y = 240, 12, 92
  pygame.draw.rect(screen, (50, 50, 50), (panel_x, bar_y, bar_w, bar_h))
  fill_w = int(min(current_squal / 128.0, 1.0) * bar_w)
  pygame.draw.rect(screen, squal_color, (panel_x, bar_y, fill_w, bar_h))
  pygame.draw.rect(screen, (180, 180, 180), (panel_x, bar_y, bar_w, bar_h), 1)

  # SQUAL History Sparkline Trace
  screen.blit(
      font.render("SQUAL History Trace", True, (200, 200, 200)), (panel_x, 114)
  )
  chart_x, chart_y, chart_w, chart_h = panel_x, 138, 240, 50
  pygame.draw.rect(screen, (35, 35, 35), (chart_x, chart_y, chart_w, chart_h))
  pygame.draw.rect(
      screen, (80, 80, 80), (chart_x, chart_y, chart_w, chart_h), 1
  )

  if len(squal_history) > 1:
    points = []
    for idx, val in enumerate(squal_history):
      px = chart_x + int((idx / (len(squal_history) - 1)) * chart_w)
      norm_val = min(val, 128) / 128.0
      py = chart_y + chart_h - int(norm_val * chart_h)
      points.append((px, py))
    if len(points) > 1:
      pygame.draw.lines(screen, squal_color, False, points, 2)

  # 2. Coordinates & Delta Section
  screen.blit(
      font_bold.render("Coordinates & Delta", True, (255, 255, 255)),
      (panel_x, 202),
  )
  screen.blit(
      font.render(f"Last dx: {last_dx}", True, (200, 200, 200)), (panel_x, 228)
  )
  screen.blit(
      font.render(f"Last dy: {last_dy}", True, (200, 200, 200)), (panel_x, 251)
  )
  screen.blit(
      font.render(f"Abs X: {abs_x}", True, (200, 200, 200)), (panel_x, 274)
  )
  screen.blit(
      font.render(f"Abs Y: {abs_y}", True, (200, 200, 200)), (panel_x, 297)
  )

  # 3. Performance & Dynamics Section
  screen.blit(
      font_bold.render("Performance Metrics", True, (255, 255, 255)),
      (panel_x, 335),
  )
  screen.blit(
      font.render(f"Speed: {current_speed_ips:.1f} IPS", True, (0, 200, 255)),
      (panel_x, 361),
  )
  screen.blit(
      font.render(f"Peak Speed: {max_speed_ips:.1f} IPS", True, (200, 200, 200)),
      (panel_x, 384),
  )
  screen.blit(
      font.render(f"Distance: {total_distance_cm:.2f} cm", True, (200, 200, 200)),
      (panel_x, 407),
  )
  screen.blit(
      font.render(f"Config DPI: {dpi}", True, (150, 150, 150)), (panel_x, 430)
  )

  # 4. Heading & Direction Domain Analysis
  screen.blit(
      font_bold.render("Kinematic Heading", True, (255, 255, 255)),
      (panel_x, 468),
  )
  screen.blit(
      font.render(
          f"Heading Angle: {current_angle_deg:.1f}°", True, (255, 200, 0)
      ),
      (panel_x, 494),
  )
  screen.blit(
      font.render(f"Direction: {cardinal_dir}", True, (200, 200, 200)),
      (panel_x, 517),
  )

  # Heading Compass Widget
  comp_cx, comp_cy, comp_r = panel_x + 120, 590, 30
  pygame.draw.circle(screen, (40, 40, 40), (comp_cx, comp_cy), comp_r)
  pygame.draw.circle(screen, (100, 100, 100), (comp_cx, comp_cy), comp_r, 1)

  rad_angle = math.radians(current_angle_deg)
  needle_x = comp_cx + int(comp_r * 0.8 * math.cos(rad_angle))
  needle_y = comp_cy - int(comp_r * 0.8 * math.sin(rad_angle))
  pygame.draw.line(
      screen, (255, 80, 80), (comp_cx, comp_cy), (needle_x, needle_y), 2
  )
  pygame.draw.circle(screen, (255, 255, 255), (comp_cx, comp_cy), 3)

  screen.blit(
      font_small.render("Heading Compass", True, (150, 150, 150)),
      (panel_x + 65, 630),
  )

  # 5. Clickable UI Buttons
  mouse_pos = pygame.mouse.get_pos()

  is_hover_rec = btn_record_rect.collidepoint(mouse_pos)
  if is_recording:
    rec_bg = (200, 40, 40) if not is_hover_rec else (230, 60, 60)
    rec_label = "🔴 Stop Recording ([R])"
  else:
    rec_bg = (0, 120, 200) if is_hover_rec else (0, 90, 150)
    rec_label = "⏺ Start Recording ([R])"

  pygame.draw.rect(screen, rec_bg, btn_record_rect, border_radius=4)
  pygame.draw.rect(
      screen,
      (255, 255, 255) if is_recording else (100, 180, 255),
      btn_record_rect,
      1,
      border_radius=4,
  )
  screen.blit(
      font_small.render(rec_label, True, (255, 255, 255)),
      (btn_record_rect.x + 12, btn_record_rect.y + 6),
  )

  is_hover_scr = btn_screenshot_rect.collidepoint(mouse_pos)
  pygame.draw.rect(
      screen,
      (70, 130, 70) if is_hover_scr else (50, 100, 50),
      btn_screenshot_rect,
      border_radius=4,
  )
  pygame.draw.rect(
      screen, (120, 200, 120), btn_screenshot_rect, 1, border_radius=4
  )
  screen.blit(
      font_small.render("📸 Screenshot ([P])", True, (255, 255, 255)),
      (btn_screenshot_rect.x + 15, btn_screenshot_rect.y + 6),
  )

  is_hover_clr = btn_clear_rect.collidepoint(mouse_pos)
  pygame.draw.rect(
      screen,
      (160, 60, 60) if is_hover_clr else (120, 40, 40),
      btn_clear_rect,
      border_radius=4,
  )
  pygame.draw.rect(
      screen, (220, 120, 120), btn_clear_rect, 1, border_radius=4
  )
  screen.blit(
      font_small.render("🗑️ Clear Stats ([C])", True, (255, 255, 255)),
      (btn_clear_rect.x + 15, btn_clear_rect.y + 6),
  )

  if save_notification and (
      pygame.time.get_ticks() - notification_time < 3000
  ):
    screen.blit(
        font_small.render(save_notification, True, (0, 255, 150)),
        (panel_x, 650),
    )

  pygame.display.flip()
  clock.tick(60)

ser.close()
pygame.quit()
sys.exit()