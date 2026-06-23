#!/bin/bash
# Switches to TTY to free GPU VRAM, runs model-factory, returns to desktop.
# Usage: ./generate.sh [creature-name]
#   e.g. ./generate.sh 9-mantorment
#        ./generate.sh          (runs all creatures)

VENV=/media/charles/5E845C27845C03C5/Projects/Games/modelGeneratorCLI/.venv/bin/model-factory
MODELS=/media/charles/5E845C27845C03C5/Projects/Games/modelGeneratorCLI/models
GUI_TTY=7
WORK_TTY=2

CREATURE=${1:-""}
LOG=/tmp/model_factory_progress.log

# Always return to GUI on exit, even on Ctrl+C or error
cleanup() {
    echo ""
    echo "Returning to desktop..."
    sudo chvt $GUI_TTY
}
trap cleanup EXIT

# Ask for sudo password upfront so it doesn't prompt mid-run
sudo -v

echo "Switching to TTY$WORK_TTY to free GPU memory..."
sudo chvt $WORK_TTY
sleep 2  # Give Xorg time to release GPU

# Build command
CMD="$VENV run --models-dir $MODELS --octree-resolution 128 --num-chunks 8000"
if [ -n "$CREATURE" ]; then
    CMD="$CMD --creature $CREATURE"
fi

echo "Running: $CMD"
echo "Progress log: $LOG"
echo ""
: > "$LOG"  # clear previous log
$CMD 2>&1 | tee "$LOG"
EXIT_CODE=${PIPESTATUS[0]}

if grep -q "0 succeeded" "$LOG"; then
    echo ""
    echo "FAILED — check errors above."
elif grep -q "succeeded" "$LOG"; then
    echo ""
    echo "SUCCESS! Generation complete."
else
    echo ""
    echo "Check output above."
fi

echo "Returning to desktop in 3 seconds..."
sleep 3
# cleanup() will run automatically via trap
