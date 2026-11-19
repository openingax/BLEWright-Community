export const fixture = Object.freeze({
  address: "02:00:00:00:00:01",
  name: "BLEWright",
  service: "0000fff0-0000-1000-8000-00805f9b34fb",
  characteristic: "0000fff1-0000-1000-8000-00805f9b34fb",
  cccd: "00002902-0000-1000-8000-00805f9b34fb",
});
export class Link {
  constructor() {
    this.state = "connecting";
    this.epoch = 0;
    this.busy = false;
    this.localNotify = false;
    this.cccd = false;
    this.value = [66, 76, 69];
    this.mtu = 23;
  }
  connected() {
    if (this.state === "connecting") this.state = "connected";
  }
  begin() {
    if (this.state !== "connected" || this.busy) return null;
    this.busy = true;
    return this.epoch;
  }
  complete(epoch) {
    if (epoch !== this.epoch || this.state !== "connected") return false;
    this.busy = false;
    return true;
  }
  disconnect() {
    this.state = "disconnected";
    this.epoch++;
    this.busy = false;
    this.localNotify = false;
    this.cccd = false;
  }
  close() {
    this.disconnect();
    this.state = "closed";
  }
  write(bytes) {
    if (bytes.length > this.mtu - 3) return 13;
    this.value = [...bytes];
    return 0;
  }
  subscribe(bytes) {
    if (bytes.length !== 2 || bytes[1] !== 0 || ![0, 1].includes(bytes[0]))
      return 6;
    this.cccd = bytes[0] === 1;
    return 0;
  }
  get notifying() {
    return this.state === "connected" && this.localNotify && this.cccd;
  }
}
