import type { ActionRequest } from "@/types/domain";

const questionTranslations: Record<string, string> = {
  "Czy kupuję prezenty, czy wyposażenie przyjęcia urodzinowego?":
    "Should I buy gifts or birthday party supplies?",
  "Jakie wymagania powinien spełniać ten zakup?":
    "What should this purchase include?",
  "Dla ilu osób mam zrobić zakupy?": "How many people should I buy for?",
  "W jakim wieku są osoby, dla których kupuję prezenty?":
    "How old are the gift recipients?",
  "Jaki jest maksymalny budżet i waluta?":
    "What is the maximum budget and currency?",
  "Na jaki dzień i godzinę potrzebna jest dostawa?":
    "What delivery date and time do you need?",
  "Do której godziny tego dnia potrzebna jest dostawa?":
    "What time should delivery arrive by?",
  "Czy potwierdzasz ten kontrakt misji?": "Do you confirm this mission?",
};

const missingDetailLabels: Record<string, string> = {
  shopping_scope: "What to buy: gifts or party supplies",
  participants: "Number of people",
  recipient_age: "Recipient age",
  budget: "Maximum budget",
  budget_currency: "Budget currency",
  deadline: "Delivery date and time",
  deadline_time: "Delivery time",
};

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

export function actionQuestion(action: ActionRequest): string {
  return questionTranslations[action.question] ?? action.question;
}

export function actionMissingDetails(action: ActionRequest): string[] {
  const missing = stringList(action.context?.missing_information);
  if (missing.length) {
    return [
      ...new Set(
        missing.map((item) => missingDetailLabels[item] ?? item.replace(/[_-]+/g, " ")),
      ),
    ];
  }
  return stringList(action.context?.questions)
    .map((question) => questionTranslations[question] ?? question);
}
