"""Gym occupancy tracker module.

Handles tracking of gym entries/exits and maintains current occupancy data.
"""

import json
import os
from datetime import datetime, timedelta
from config import DATA_FILE, MAX_GYM_CAPACITY, OCCUPANCY_LEVELS


class GymTracker:
    """Tracks gym occupancy using student card tap data."""

    def __init__(self, data_file: str = DATA_FILE):
        self.data_file = data_file
        self.data = self._load_data()

    def _load_data(self) -> dict:
        """Load gym data from JSON file."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return self._create_new_data()
        return self._create_new_data()

    def _create_new_data(self) -> dict:
        """Create new gym data structure."""
        return {
            "current_occupancy": 0,
            "total_entries_today": 0,
            "total_exits_today": 0,
            "last_updated": datetime.now().isoformat(),
            "history": [],  # Stores recent activity
            "entries": {},  # Track who is currently inside {student_id: entry_time}
        }

    def save_data(self) -> None:
        """Save current gym data to JSON file."""
        self.data["last_updated"] = datetime.now().isoformat()
        with open(self.data_file, "w") as f:
            json.dump(self.data, f, indent=2)

    def record_entry(self, student_id: str) -> dict:
        """Record a student entering the gym (simulates card tap)."""
        now = datetime.now()
        
        # If student is already inside, update their entry time
        if student_id in self.data.get("entries", {}):
            return {
                "success": False,
                "message": f"Student {student_id} is already inside the gym.",
                "type": "already_inside"
            }

        # Check if gym is at capacity
        current = self.data.get("current_occupancy", 0)
        if current >= MAX_GYM_CAPACITY:
            return {
                "success": False,
                "message": "Gym is at full capacity! Entry denied.",
                "type": "at_capacity"
            }

        # Record entry
        if "entries" not in self.data:
            self.data["entries"] = {}
        
        self.data["entries"][student_id] = now.isoformat()
        self.data["current_occupancy"] = current + 1
        
        # Update today's stats
        self.data["total_entries_today"] = self.data.get("total_entries_today", 0) + 1

        # Add to activity history
        activity = {
            "timestamp": now.isoformat(),
            "type": "entry",
            "student_id": student_id,
            "occupancy_after": self.data["current_occupancy"]
        }
        self.data.setdefault("history", []).append(activity)
        
        # Keep only last 100 activities
        self.data["history"] = self.data["history"][-100:]

        self.save_data()

        return {
            "success": True,
            "message": f"Entry recorded for student {student_id}",
            "type": "entry",
            "current_occupancy": self.data["current_occupancy"],
            "percentage": self._get_occupancy_percentage()
        }

    def record_exit(self, student_id: str) -> dict:
        """Record a student exiting the gym."""
        now = datetime.now()

        # Check if student is inside
        if student_id not in self.data.get("entries", {}):
            return {
                "success": False,
                "message": f"Student {student_id} is not inside the gym.",
                "type": "not_inside"
            }

        # Remove from entries
        del self.data["entries"][student_id]
        
        # Update occupancy
        current = max(0, self.data.get("current_occupancy", 0) - 1)
        self.data["current_occupancy"] = current

        # Update today's stats
        self.data["total_exits_today"] = self.data.get("total_exits_today", 0) + 1

        # Add to activity history
        activity = {
            "timestamp": now.isoformat(),
            "type": "exit",
            "student_id": student_id,
            "occupancy_after": current
        }
        self.data.setdefault("history", []).append(activity)
        self.data["history"] = self.data["history"][-100:]

        self.save_data()

        return {
            "success": True,
            "message": f"Exit recorded for student {student_id}",
            "type": "exit",
            "current_occupancy": current,
            "percentage": self._get_occupancy_percentage()
        }

    def get_status(self) -> dict:
        """Get current gym status."""
        occupancy = self.data.get("current_occupancy", 0)
        percentage = self._get_occupancy_percentage()
        level = self._get_occupancy_level(occupancy)

        return {
            "current_occupancy": occupancy,
            "max_capacity": MAX_GYM_CAPACITY,
            "percentage": percentage,
            "level": level,
            "total_entries_today": self.data.get("total_entries_today", 0),
            "total_exits_today": self.data.get("total_exits_today", 0),
            "last_updated": self.data.get("last_updated", "N/A"),
            "recent_activity": self.data.get("history", [])[-5:]  # Last 5 activities
        }

    def get_occupancy_level(self) -> str:
        """Get the current occupancy level string."""
        occupancy = self.data.get("current_occupancy", 0)
        return self._get_occupancy_level(occupancy)

    def _get_occupancy_level(self, occupancy: int) -> dict:
        """Get the occupancy level description based on count."""
        percentage = (occupancy / MAX_GYM_CAPACITY) * 100 if MAX_GYM_CAPACITY > 0 else 0
        
        for level_name, level_info in OCCUPANCY_LEVELS.items():
            if level_info["min"] <= percentage <= level_info["max"]:
                return level_info
        
        # Default to low if under 0%
        if percentage < 0:
            return OCCUPANCY_LEVELS["low"]
        # Default to full if over 100%
        return OCCUPANCY_LEVELS["full"]

    def _get_occupancy_percentage(self) -> int:
        """Calculate current occupancy as a percentage of max capacity."""
        occupancy = self.data.get("current_occupancy", 0)
        return round((occupancy / MAX_GYM_CAPACITY) * 100) if MAX_GYM_CAPACITY > 0 else 0

    def reset_for_new_day(self) -> dict:
        """Reset daily counters for a new day."""
        old_entries = self.data.get("total_entries_today", 0)
        old_exits = self.data.get("total_exits_today", 0)
        
        # Save end-of-day summary to history
        self.data["history"].append({
            "timestamp": datetime.now().isoformat(),
            "type": "day_reset",
            "final_occupancy": self.data.get("current_occupancy", 0),
            "total_entries": old_entries,
            "total_exits": old_exits
        })

        # Reset counters but keep entries (people still inside)
        self.data["total_entries_today"] = 0
        self.data["total_exits_today"] = 0
        self.data["current_occupancy"] = len(self.data.get("entries", {}))
        
        self.save_data()

        return {
            "previous_entries": old_entries,
            "previous_exits": old_exits,
            "carried_over": self.data["current_occupancy"]
        }

    def get_recent_activity(self, limit: int = 10) -> list:
        """Get recent gym activity."""
        history = self.data.get("history", [])
        return history[-limit:] if history else []