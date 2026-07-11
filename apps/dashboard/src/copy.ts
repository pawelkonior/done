/** English display copy for the common Polish mission titles used by the local demo. */
export function displayMissionTitle(title: string): string {
  const birthdayShopping = /^Kup tort, balony, dekoracje i soki na urodziny dla (\d+) dzieci/i.exec(title);
  if (birthdayShopping) {
    return `Buy cake, balloons, decorations and juice for a birthday party for ${birthdayShopping[1]} children, tomorrow by the requested deadline`;
  }

  const birthdayPlanning = /^Zorganizuj urodziny dla (\d+) dzieci/i.exec(title);
  if (birthdayPlanning) {
    return `Plan a birthday party for ${birthdayPlanning[1]} children, tomorrow by the requested deadline`;
  }

  return title;
}
