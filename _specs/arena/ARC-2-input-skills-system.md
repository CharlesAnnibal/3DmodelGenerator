---
status: planned
---

# ARC-2 — Input Mapping & Skills System

## Problem
The Arena has a raw input map and a movement controller but no layer between them that understands creatures, states, or skills. `Attack` just locks the cursor. `Sprint` is defined but never read in code. There is no concept of a creature having specific abilities, no cooldown management, and no contextual behaviour (grounded vs airborne variant of the same skill).

## Goal
A data-driven skills layer sits on top of the existing KCC movement system. Game feel is 3rd-person action like Legend of Zelda — free movement + directional camera + skill buttons. Each creature has exactly 4 skills (Attack + Skill1 + Skill2 + Skill3), one of which is a basic attack with no cooldown. Skills are defined in ScriptableObjects per creature — no code change to add or modify a skill set. Skills respect context: the same button pressed while airborne can trigger a different animation than when grounded.

## Input layout

### Keyboard & Mouse

| Action | Key | Notes |
|--------|-----|-------|
| Move | WASD / Arrows | already wired |
| Look | Mouse delta | already wired |
| Jump | Space | already wired |
| Sprint | Left Shift (hold) | in map, NOT wired in code yet |
| Attack | Left Click | basic attack, no cooldown |
| Skill1 | Q | new binding |
| Skill2 | E | new binding |
| Skill3 | R | new binding |
| Crouch | C | in map, future ticket |

### Gamepad

| Action | Button | Notes |
|--------|--------|-------|
| Move | Left stick | already wired |
| Look | Right stick | already wired |
| Jump | South (A/Cross) | already wired |
| Sprint | Left stick press | in map, NOT wired |
| Attack | West (X/Square) | basic attack |
| Skill1 | Right Bumper (RB/R1) | new binding |
| Skill2 | Left Bumper (LB/L1) | new binding |
| Skill3 | North (Y/Triangle) | freed from Interact |

## Scope

### In scope
- 4 skill slots per creature: Attack (no cooldown) + Skill1 + Skill2 + Skill3
- Sprint wired to locomotion speed
- `CreatureSkill` and `CreatureData` ScriptableObjects
- `SkillController` MonoBehaviour
- Input action map changes (add Skill1/2/3, remove Interact)
- `PlayerCharacterInputs` struct extended with skill and sprint fields
- `MyCharacterController` exposes `IsGrounded`, splits walk/sprint speeds
- Contextual skill variants (grounded clip vs airborne clip)
- Cooldown tracking per skill slot

### Out of scope
- `Interact` action — removed; no hold-to-interact mechanic planned
- Crouch — future ticket
- Skill effects / hit detection / damage — animations only
- Combo chaining on Attack
- Skill UI / cooldown display — future ticket (cooldown data in ScriptableObject from day one)
- Avian locomotion — future ticket

## Data model

### `CreatureSkill` (ScriptableObject)

```
skillName          string
groundedClip       AnimationClip        — plays when grounded
airborneClip       AnimationClip        — plays when airborne; null = use groundedClip
inputSlot          enum { Attack, Skill1, Skill2, Skill3 }
cooldown           float (seconds)      — 0 for Attack
```

### `CreatureData` (ScriptableObject)

```
creatureName       string
rigProfile         enum { Humanoid, Quadruped, Serpentine }

— locomotion clips —
idleClip           AnimationClip
walkClip           AnimationClip
runClip            AnimationClip
jumpClip           AnimationClip
fallClip           AnimationClip
landClip           AnimationClip

— skills —
attackSkill        CreatureSkill
skill1             CreatureSkill
skill2             CreatureSkill
skill3             CreatureSkill
```

## Code changes

### `PlayerCharacterInputs` struct

```csharp
// existing
float MoveAxisForward;
float MoveAxisRight;
Quaternion CameraRotation;
bool JumpDown;
// add
bool SprintHeld;
bool AttackDown;
bool Skill1Down;
bool Skill2Down;
bool Skill3Down;
```

### `MyPlayer.cs`
- Add `_sprintAction`, `_skill1Action`, `_skill2Action`, `_skill3Action` fields
- Bind from `Player` action map in `OnEnable`
- Write into `PlayerCharacterInputs` each frame
- Remove cursor-lock hack from attack handling (moves to `SkillController`)

### `MyCharacterController.cs`
- Replace `MaxStableMoveSpeed` with `WalkSpeed` + `SprintSpeed`
- Target speed = `SprintHeld ? SprintSpeed : WalkSpeed`
- Add `public bool IsGrounded => Motor.GroundingStatus.IsStableOnGround`

### `SkillController.cs` (new)
- Holds `CreatureData` reference and `Animator` reference
- Ticks cooldown timers each frame
- On skill input: check cooldown → pick grounded/airborne clip → trigger Animator → reset timer
- Drives `Speed`, `IsGrounded`, `SkillTrigger`, `SkillIndex` Animator parameters

## Input action map changes

1. Add action `Skill1` — `<Keyboard>/q`, `<Gamepad>/rightShoulder`
2. Add action `Skill2` — `<Keyboard>/e`, `<Gamepad>/leftShoulder`
3. Add action `Skill3` — `<Keyboard>/r`, `<Gamepad>/buttonNorth`
4. Delete action `Interact`
5. `Sprint` and `Attack` — no binding changes

## Acceptance criteria
- [ ] Holding Left Shift increases speed; releasing returns to walk
- [ ] Left Click fires Attack animation with no cooldown
- [ ] Q / E / R fire Skill1 / Skill2 / Skill3 animations
- [ ] Skills with cooldown > 0 cannot re-trigger until timer expires
- [ ] Skill pressed while airborne plays `airborneClip` when set, otherwise `groundedClip`
- [ ] Swapping `CreatureData` changes all 4 skills with no code change
- [ ] `MyCharacterController` has no direct `UnityEngine.InputSystem` reference

## Constraints
- KCC owns velocity — skills are animation-only, no physics impulse
- `PlayerCharacterInputs` is the only data path from `MyPlayer` to controllers

## Open questions
- Skill moves for each creature must be defined before animation clips can be sourced. Spec each creature's skills individually before implementing.
