---
status: draft
---

# ARC-2 — Link walk animation from 3d model to the current movement engine (action)

## Problem
Generated creatures are static GLBs dropped into a Unity scene with no animations. The Arena has movement physics (KCC) but no Animator, no locomotion clips — creatures slide around like frozen statues.

We already have two scripts taking care about the basic movement and camera `CreatureController.cs` and `PlayerInputHandler.cs`

## Goal
1. Create a definition on the project about what is basic movements, skills , actions , etc. Definition of concept. Can write it in a CLAUDE.md , README.md .

- Actions : Anything that a creature can do.
- Skills : The 4 habilities. Q W E R
- Movements: Walk, run, jump, avoid(future) crouch(future), fly(future), dive(very future)

2. Create a claude skill to connect the 3dmodel animation, animator and  action

3. When we start to walk, play the walk animation

4. When we press to jump, play the jump animation

Move the movement scripts to a better folder into `Scripts`. Think in a folder name.
## Scope
Definition of concepts
Walk with animation

## Out of scope 
- Run . We will map another animation on the future
- Control of velocity - In the future, many variables will change the velocity. For now, let's just make a creature move around the map.