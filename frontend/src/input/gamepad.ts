import type { Action } from './actions';

const BUTTONS: Record<number, Action> = {
  0: 'confirm', 1: 'back', 3: 'controls', 4: 'sectionPrev', 5: 'sectionNext',
  6: 'seekBack', 7: 'seekForward', 9: 'pause',
  12: 'up', 13: 'down', 14: 'left', 15: 'right',
};
const REPEATING = new Set<Action>(['up', 'down', 'left', 'right', 'seekBack', 'seekForward']);
export class GamepadInput {
  private held = new Map<Action, number>();
  private suspended = false;
  reset(suppressHeld = false) { this.held.clear(); this.suspended = suppressHeld; }
  sample(pads: (Gamepad | null)[], now: number, active: boolean): Action[] {
    if (!active) { this.reset(true); return []; }
    const pressed = new Set<Action>();
    for (const pad of pads) {
      if (!pad?.connected || (pad.mapping && pad.mapping !== 'standard')) continue;
      for (const [index, action] of Object.entries(BUTTONS)) {
        const button = pad.buttons[Number(index)];
        if (button && (button.pressed || button.value > 0.55)) pressed.add(action);
      }
      const [x = 0, y = 0] = pad.axes;
      if (Math.abs(x) >= Math.abs(y) && Math.abs(x) > 0.55) pressed.add(x < 0 ? 'left' : 'right');
      else if (Math.abs(y) > 0.55) pressed.add(y < 0 ? 'up' : 'down');
    }
    if (this.suspended) {
      for (const action of pressed) this.held.set(action, Infinity);
      this.suspended = false;
    }
    for (const action of this.held.keys()) if (!pressed.has(action)) this.held.delete(action);
    const actions: Action[] = [];
    for (const action of pressed) {
      const due = this.held.get(action);
      if (due === undefined || (REPEATING.has(action) && now >= due)) {
        actions.push(action);
        this.held.set(action, now + (due === undefined ? 380 : 110));
      }
    }
    return actions;
  }
}
