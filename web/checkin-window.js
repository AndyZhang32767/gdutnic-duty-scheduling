/* Check-in window rules shared by the member page and the Node tests.
   Opens `early` minutes before the shift start and closes at the shift end. */
(function (root) {
  function canCheckIn(range, limits, now = Date.now()) {
    return !!range && now >= range.start - limits.early && now < range.end;
  }
  function checkInLabel(range, limits, now = Date.now()) {
    if (!canCheckIn(range, limits, now)) return '未在签到时间内';
    if (now >= range.start + limits.absent) return '确认到岗签到（已记为未到岗）';
    if (now >= range.start + limits.late) return '确认到岗签到（迟到）';
    return '确认到岗签到';
  }
  function syncCheckInButton(submit, range, limits, now = Date.now()) {
    submit.disabled = !canCheckIn(range, limits, now);
    submit.textContent = checkInLabel(range, limits, now);
  }
  Object.assign(root, {canCheckIn, checkInLabel, syncCheckInButton});
})(typeof window !== 'undefined' ? window : globalThis);

if (typeof module === 'object' && module.exports) module.exports = {canCheckIn, checkInLabel};
