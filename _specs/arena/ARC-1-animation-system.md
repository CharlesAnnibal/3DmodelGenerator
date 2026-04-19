---
status: in-progress
---

# ARC-1 — Creature Animation System

## Problem
Generated creatures are static GLBs dropped into a Unity scene with no animations. The Arena has movement physics (KCC) but no Animator, no locomotion clips — creatures slide around like frozen statues.

## Goal
Each creature can idle, walk, run, and jump. Locomotion animations are driven automatically by movement speed. The system works for all three rig profiles: humanoid, quadruped, and serpentine. No manual animation authoring required.

## Scope

### In scope
- Animator setup on each creature GLB
- Locomotion state machine for humanoid: Idle → Walk → Run blend tree (parameter: Speed), Jump, Fall, Land
- Procedural locomotion for quadruped: four `TwoBoneIKConstraint`s driven by `QuadrupedLocomotion.cs` (trot gait, diagonal pairs)
- Procedural locomotion for serpentine: `SerpentineLocomotion.cs` (spine sine wave, LateUpdate)
- Animator Controller template per rig profile (humanoid / quadruped / serpentine)
- One creature wired end-to-end as proof of concept (empalynx — quadruped)

### Out of scope
- Link movement animations to `CreatureController.cs` beyond `AnimatorDriver` — covered in ARC-2
- Skill/attack animations — covered in ARC-5
- Avian / flying locomotion — future ticket
- Root motion — KCC owns velocity; animations are cosmetic only
- Multiplayer animation sync
- Facial animations
- Terrain-adaptive foot IK (raycast per foot) — future improvement to QuadrupedLocomotion

## Animation source per rig profile

| Profile | Approach | Why |
|---|---|---|
| `humanoid` | Mixamo — download idle/walk/run/jump pack (Without Skin), configure Humanoid avatar in Unity | Free, Humanoid-compatible; no upload needed since Generic Humanoid clips retarget automatically |
| `quadruped` | Procedural — 4× `TwoBoneIKConstraint` driven by `QuadrupedLocomotion.cs` | No clip standard for quads; TwoBoneIK is already in Animation Rigging 1.4.1; trot gait in ~80 lines of C# |
| `serpentine` | Procedural — spine sine wave via `SerpentineLocomotion.cs` | No clip-based standard exists; driven in LateUpdate |

## Rig bone names

### Quadruped (`FrontLeft`, `FrontRight`, `BackLeft`, `BackRight` per leg)
- Spine: `Hips` → `Spine` → `Neck` → `Head`
- Per leg: `{Side}UpperLeg` → `{Side}LowerLeg` → `{Side}Foot`
- Each leg is a 3-bone chain — maps directly to one `TwoBoneIKConstraint`

### Serpentine
- `Spine01` → `Spine02` → … → `Spine08`

### Humanoid (future)
- `Hips`, `Spine`, `Neck`, `Head`
- `LeftUpperArm`, `LeftLowerArm`, `LeftHand` (and Right equivalents)
- `LeftUpperLeg`, `LeftLowerLeg`, `LeftFoot` (and Right equivalents)

## Animator Controller layout

### Humanoid — `HumanoidLocomotion.controller`
Two layers:

| Layer | Weight | Mode | Drives |
|-------|--------|------|--------|
| Base | 1.0 | Override | Idle/Walk/Run blend tree; Jump; Fall; Land |
| Skills | 1.0 | Override | Empty placeholder — wired in ARC-2 |

Base layer blend tree (parameter: `Speed`):
```
0.0      → Idle
0.0–0.5  → Walk (blend)
0.5–1.0  → Run  (blend)
```

Parameters: `Speed` (Float), `IsGrounded` (Bool), `VelocityY` (Float), `Land` (Trigger)

Transitions:
```
BlendTree → Jump:   IsGrounded == false, VelocityY > 0
BlendTree → Fall:   IsGrounded == false, VelocityY ≤ 0
Jump      → Fall:   VelocityY ≤ 0
Fall      → Land:   IsGrounded == true  (Land trigger)
Land      → BlendTree: exit time (~0.3s)
```

### Quadruped / Serpentine — stub controllers
Single empty state. Movement is driven entirely by `QuadrupedLocomotion.cs` / `SerpentineLocomotion.cs` in LateUpdate. Controller exists to satisfy `Animator` component requirement.

## Scripts

| Script | Purpose |
|---|---|
| `Movement/AnimatorDriver.cs` | Reads `Motor.Velocity` + `GroundingStatus` → pushes Speed, IsGrounded, VelocityY, Land to Animator each frame. Used by humanoid creatures. |
| `Movement/QuadrupedLocomotion.cs` | Procedural trot gait. 4× `TwoBoneIKConstraint` targets moved in diagonal-pair steps. Scales frequency/amplitude with speed. |
| `Movement/SerpentineLocomotion.cs` | Sine wave along `Transform[] spineChain`. Amplitude scales with speed. |
| `Editor/AnimatorControllersSetup.cs` | **Arena > Setup > Create Animator Controllers** — creates all 3 controllers under `Assets/Animations/`. Safe to re-run. |
| `Editor/QuadrupedRigSetup.cs` | **Arena > Setup > Setup Quadruped Rig (Select Root)** — select creature root in Hierarchy, runs to add RigBuilder, 4× TwoBoneIKConstraint, and wire QuadrupedLocomotion automatically. |

## Bone Renderer artifact (answered)
Worcomb bones appearing "only on the head" in Unity's Bone Renderer is a visual editor artifact — the armature root is placed at the mesh origin, which gltfast maps near the model's head pivot. Does NOT affect skinning or runtime deformation. `SerpentineLocomotion.cs` drives transforms directly in LateUpdate regardless of where Bone Renderer draws them. Safe to ignore.

## Unity setup — empalynx (proof of concept)

GLB import is already Generic (`animationMethod: 2` in .meta). No Rig tab change needed.

**Steps (all automated except Animator assignment):**

1. **Menu: Arena > Setup > Create Animator Controllers**
   Creates `QuadrupedLocomotion.controller`, `SerpentineLocomotion.controller`, `HumanoidLocomotion.controller` in `Assets/Animations/`.

2. **Select empalynx root in Hierarchy → Menu: Arena > Setup > Setup Quadruped Rig (Select Root)**
   Automatically: adds RigBuilder, creates Rig hierarchy, adds 4× TwoBoneIKConstraint with Target/Hint GOs, adds QuadrupedLocomotion, wires all bone references and bodyRoot.

3. **Manual: assign Animator Controller**
   Select empalynx root → add `Animator` component → Controller: `QuadrupedLocomotion` → Apply Root Motion: OFF.

4. **Manual: assign CreatureController reference**
   In `QuadrupedLocomotion` Inspector → `Character Controller` field → drag the `CreatureController` component.

**Worcomb:**
1. Select worcomb root → add `Animator` → Controller: `SerpentineLocomotion` → Apply Root Motion: OFF
2. Add `SerpentineLocomotion` → drag `Spine01`–`Spine08` into Spine Chain → assign `CreatureController`

## Acceptance criteria
- [ ] Empalynx feet step in a trot gait when WASD held — diagonal pairs alternate
- [ ] Empalynx feet are still when idle
- [ ] Worcomb spine undulates when moving, still when idle
- [ ] All three Animator Controller stubs exist (HumanoidLocomotion, QuadrupedLocomotion, SerpentineLocomotion)
- [ ] Root motion is OFF on all Animators
- [ ] `AnimatorDriver.cs` ready for humanoid creatures (wired when first humanoid arrives)

## Constraints
- Root motion off — KCC owns velocity
- Generic avatar for quadruped/serpentine; Humanoid only for humanoid profile
- `QuadrupedLocomotion` and `SerpentineLocomotion` run in LateUpdate (after KCC physics)

## Dependencies
- MGC-8 (done): FBX export + rig manifest
- ARC-2: `CreatureData` ScriptableObject that holds clip references (humanoid only)
