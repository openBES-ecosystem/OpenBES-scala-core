# Active Hours Semantics Analysis

## Summary

The `active_hours` field in OpenBES represents the operating time period of a system each day using 24-hour format (1-24 or 0-23). The semantics are:
- `start`: Hour when the system turns ON
- `end`: Hour when the system turns OFF

**Current implementation does NOT support overnight/wrapped times** (e.g., start=17, end=8 for "5 PM to 8 AM next day").

---

## Data Locations & Usage

### Field Definitions

The `active_hours` is defined as a `Duration` object in [src/openbes/schemas/generated/models.py](src/openbes/schemas/generated/models.py#L283-L284):

```python
class Duration(BaseModel):
    start: int = Field(..., description="Start hour (1-24).")
    end: int = Field(..., description="End hour (1-24).")
```

Fields are used in:
- **Zones** (occupancy): `zone.active_hours` → occupancy_open/close times
- **Heating Systems**: `heating_system{n}.active_hours` → heating_system{n}_on/off_time
- **Cooling Systems**: `cooling_system{n}.active_hours` → cooling_system{n}_on/off_time  
- **Ventilation Systems**: `ventilation_system{n}.active_hours` → ventilation_system{n}_on/off_time
- **Lighting (at building level)**: `lighting_active_hours` → lighting_on/off_time

### Conversion Format

In TOML format:
```toml
heating_system1_on_time = 8      # corresponds to active_hours.start
heating_system1_off_time = 17    # corresponds to active_hours.end
```

In JSON format:
```json
"heating_systems": [{
  "active_hours": {
    "start": 8,
    "end": 17
  }
}]
```

**See**: [json_to_toml.py](src/openbes/schemas/conversion/json_to_toml.py#L390-L391) and [toml_to_json.py](src/openbes/schemas/conversion/toml_to_json.py#L115-L124)

---

## Typical Patterns in Test Cases

### ASHRAE Test Cases (600, 650, 680, etc.)

**Heating/Cooling Systems**: Typically **empty/null** - no active_hours defined
```toml
# Example from 600.toml
"d.heating_system1_on_time" = ""
"d.heating_system1_off_time" = ""
"d.cooling_system1_on_time" = ""
"d.cooling_system1_off_time" = ""
```

**Zone Occupancy**: Specific to each zone
```toml
# From 600.toml - Office area occupancy
"i.occupancy_open_office" = 1      # Hour 1 (midnight start)
"i.occupancy_close_office" = 24    # Hour 24 (end of day)

# From 600.toml - Common areas
"i.occupancy_open_common" = 1
"i.occupancy_close_common" = 24
```

### Real Building Examples (Holywell House)

**Zone Occupancy** - Varies by functional area:
```json
{
  "name": "Office area",
  "active_hours": {"start": 8, "end": 17}      # 8 AM to 5 PM
},
{
  "name": "Teaching",
  "active_hours": {"start": 9, "end": 17}      # 9 AM to 5 PM
},
{
  "name": "Canteen",
  "active_hours": {"start": 10, "end": 14}     # 10 AM to 2 PM
},
{
  "name": "Common areas",
  "active_hours": null                         # No specific hours
}
```

**Heating System** - ⚠️ **REVERSED HOURS**:
```json
{
  "type": "Condensing boiler",
  "active_hours": {"start": 17, "end": 8}      # 5 PM to 8 AM NEXT DAY
}
```

**Cooling System** - Normal hours:
```json
{
  "type": "Heat pump",
  "active_hours": {"start": 8, "end": 17}      # 8 AM to 5 PM
}
```

---

## Implementation Details

### How Active Hours Are Used

#### 1. **Lighting** ([lighting.py#L188-L190](src/openbes/simulations/lighting.py#L188-L190))
```python
on_time = self.spec.lighting_on_time
off_time = self.spec.lighting_off_time
if on_time is not None and off_time is not None:
    i = s.index.get_level_values("hour")
    lights_on = (i > on_time) & (i <= off_time)  # Simple range check
    self._hours["lights_on"] = logical_and(s, lights_on)
```

#### 2. **Ventilation** ([ventilation.py#L96](src/openbes/simulations/ventilation.py#L96))
```python
lambda x: on_time <= x <= off_time  # Simple range check
```

#### 3. **Heating/Cooling Systems**
Currently DO NOT directly use `active_hours` in calculations. Instead, they use:
- `self.occupancy.is_occupied` for determining when system operates
- System operates when building is occupied AND temperature exceeds thresholds

---

## Critical Finding: Reversed Hours (17-8 Pattern)

The holywell_house.json contains:
```json
"heating_systems": [{
  "active_hours": {"start": 17, "end": 8}  # 5 PM to 8 AM
}]
```

### Issues with Current Implementation

1. **Lighting Logic**: `(i > 17) & (i <= 8)` evaluates to FALSE for ALL hours
   - No hour satisfies both conditions
   - Lights would never turn on

2. **Ventilation Logic**: `17 <= x <= 8` evaluates to FALSE for ALL hours
   - No hour satisfies the range
   - Ventilation would never run

3. **No Wraparound Handling**: The code uses simple comparison operators without checking if start > end

### Likely Intent

The pattern `{"start": 17, "end": 8}` likely means:
- **Night heating**: Active from 5 PM (hour 17) through 8 AM (hour 8) next day
- This is common in buildings that heat overnight and cool/ventilate during day

### Current Workaround in Code

Since heating/cooling systems don't directly use active_hours (they use occupancy-based control), this bug doesn't affect them. However, if the fields were ever used directly (e.g., for system scheduling), it would fail.

---

## Code Comments About Active Hours

From schema documentation:
- **Zone**: "Times the zone is occupied each day"
- **Heating/Cooling**: "Times the system is on each day"
- **Ventilation**: "Times the system is on each day"

The field descriptions assume simple start→end semantics without wraparound.

---

## Recommendations

### For Backward Compatibility

The holywell_house.json data suggests users may expect reversed hours to work. Consider:

1. **Add wraparound logic** where start > end means "overnight period":
   ```python
   if on_time <= off_time:
       hours_active = (hour >= on_time) & (hour <= off_time)
   else:  # Wraparound
       hours_active = (hour >= on_time) | (hour <= off_time)
   ```

2. **Document the behavior** clearly in schema descriptions

3. **Add validation** to warn users if start > end is used (to clarify intent)

4. **Add tests** for both normal (8-17) and overnight (17-8) patterns

---

## Test Case Summary Table

| Test Case | Heating On/Off | Cooling On/Off | Zone Example | Pattern |
|-----------|---|---|---|---|
| ASHRAE 600 | Empty | Empty | office: 1-24 | No system active_hours |
| Holywell House | **17-8** ⚠️ | 8-17 | office: 8-17 | Reversed heating (overnight) |
| Semi-detached | Various | Various | office: 8-18 | Normal business hours |

---

## Files Involved

- **Models**: [src/openbes/schemas/generated/models.py](src/openbes/schemas/generated/models.py#L283-L284)
- **Conversion**: [json_to_toml.py](src/openbes/schemas/conversion/json_to_toml.py), [toml_to_json.py](src/openbes/schemas/conversion/toml_to_json.py)
- **Usage**: 
  - [lighting.py](src/openbes/simulations/lighting.py#L188-L190) - active_hours used for lights_on
  - [ventilation.py](src/openbes/simulations/ventilation.py#L96) - active_hours used for ventilation_on
  - [heating.py](src/openbes/simulations/heating.py) - Does NOT use active_hours
  - [cooling.py](src/openbes/simulations/cooling.py) - Does NOT use active_hours
- **Test Data**:
  - [holywell_house.json](src/openbes/example_data/holywell_house.json) - Contains reversed heating hours
  - [ASHRAE test cases](tests/test_cases/cases/) - Mostly empty active_hours

---

**Analysis Date**: 2026-09-08  
**Key Finding**: Reversed active_hours (start > end) exist in production data but current implementation doesn't handle wraparound midnight crossing.
