/**
 * How to get your own messages out of each social: the export each one lets you download, in a few short steps. What
 * reads them is app/utils/chatexports.py, so a social goes on this list once that can read its file. iMessage has no
 * export, and what is said in Minecraft is not how anyone texts.
 *
 * The labels are the socials' own as of November 2026 (their help pages, and guides where those would not say). They do
 * move them around, which is why each has a link to the place itself where there is one.
 */
export type Guide = {
  id: string;
  name: string;
  /** How long it takes them, in a few words. */
  wait: string;
  steps: string[];
  link?: { url: string; text: string };
  /** The one thing worth knowing before starting. */
  note?: string;
};

export const GUIDES: Guide[] = [
  {
    id: "discord",
    name: "Discord",
    wait: "Up to 30 days",
    steps: [
      "In Discord, open Settings, then Data & Privacy.",
      "Press Request all of my data.",
      "Tick only Messages, then Request My Data.",
      "When the email comes, download the zip and drop it here.",
    ],
    link: { url: "https://support.discord.com/hc/en-us/articles/360004027692", text: "Discord's help" },
    note: "Often a day or two. It only has servers you are still in.",
  },
  {
    id: "telegram",
    name: "Telegram",
    wait: "Right away",
    steps: [
      "Open Telegram Desktop, on a computer.",
      "Settings, Advanced, Export Telegram data.",
      "Tick Personal chats, and untick photos and videos.",
      "Set the format to Machine-readable JSON, then Export.",
      "Drop result.json here.",
    ],
    link: { url: "https://desktop.telegram.org/", text: "Get Telegram Desktop" },
  },
  {
    id: "whatsapp",
    name: "WhatsApp",
    wait: "Right away",
    steps: [
      "Open a chat you talk in a lot.",
      "On Android: the three dots, More, Export chat. On iPhone: its name, Export chat.",
      "Pick Without media, and send it to yourself.",
      "Drop it here, then do the same with another chat.",
    ],
    link: { url: "https://faq.whatsapp.com/1180414079177245", text: "WhatsApp's help" },
    note: "One chat at a time. It takes two or more to tell which messages are yours.",
  },
  {
    id: "snapchat",
    name: "Snapchat",
    wait: "Up to 7 days",
    steps: [
      "Open My Data and sign in.",
      "Tick Saved Chat History, and turn on the JSON option.",
      "Turn the date range off to get all of it, then Submit.",
      "When the email comes, download the zip and drop it here.",
    ],
    link: { url: "https://accounts.snapchat.com/v2/download-my-data", text: "Open My Data" },
    note: "Only messages you or they saved are in it.",
  },
  {
    id: "instagram",
    name: "Instagram",
    wait: "Up to 2 days",
    steps: [
      "Open Accounts Center. It may say Meta Account.",
      "Your information and permissions, then Export your information.",
      "Create export, pick your Instagram, Export to device.",
      "Customize information: only Messages. Format: JSON. Start export.",
      "When it is ready, download the zip and drop it here.",
    ],
    link: { url: "https://accountscenter.instagram.com/info_and_permissions/dyi/", text: "Open Accounts Center" },
    note: "End-to-end encrypted chats are a separate download, and are not read.",
  },
  {
    id: "tiktok",
    name: "TikTok",
    wait: "1 to 4 days",
    steps: [
      "Open Settings and privacy, Account, Download your data.",
      "Pick JSON, and include your direct messages.",
      "Request data, then look in the Download tab when it is ready.",
      "Drop the file here.",
    ],
    link: { url: "https://www.tiktok.com/setting/download-your-data", text: "Open it" },
  },
  {
    id: "x",
    name: "X",
    wait: "A day or more",
    steps: [
      "Open Settings and privacy, Your account, Download an archive of your data.",
      "Confirm it is you, then Request archive.",
      "When it says it is ready, download the zip and drop it here.",
    ],
    link: { url: "https://x.com/settings/download_your_data", text: "Open it" },
  },
  {
    id: "reddit",
    name: "Reddit",
    wait: "Up to 30 days",
    steps: [
      "Open Settings, Data request, and sign in.",
      "Ask for your data. It comes as a message on Reddit.",
      "Download the zip and drop it here.",
    ],
    link: { url: "https://www.reddit.com/settings/data-request", text: "Open it" },
    note: "Your chats and comments both count. You can only ask once every 30 days.",
  },
];

/** The fewest messages of yours it can tell anything from. app/utils/chatpersona.py says the same (MIN_MESSAGES). */
export const ENOUGH = 30;
