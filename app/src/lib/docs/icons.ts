/* Icons a docs page may name in its frontmatter (`icon: compass`) or an alert may name in its
 * attributes (`:::alert[Title]{icon=lock}`). A fixed list, because lucide icons are imported one
 * by one; an unknown name falls back to a generic page icon rather than failing the page. */

import type { Component } from "svelte";
import BookOpenIcon from "@lucide/svelte/icons/book-open";
import CircleHelpIcon from "@lucide/svelte/icons/circle-help";
import ClockIcon from "@lucide/svelte/icons/clock";
import CompassIcon from "@lucide/svelte/icons/compass";
import DatabaseIcon from "@lucide/svelte/icons/database";
import FileTextIcon from "@lucide/svelte/icons/file-text";
import FlaskConicalIcon from "@lucide/svelte/icons/flask-conical";
import FolderIcon from "@lucide/svelte/icons/folder";
import HistoryIcon from "@lucide/svelte/icons/history";
import InfoIcon from "@lucide/svelte/icons/info";
import KeyRoundIcon from "@lucide/svelte/icons/key-round";
import LightbulbIcon from "@lucide/svelte/icons/lightbulb";
import LinkIcon from "@lucide/svelte/icons/link";
import LockIcon from "@lucide/svelte/icons/lock";
import PackageIcon from "@lucide/svelte/icons/package";
import PencilIcon from "@lucide/svelte/icons/pencil";
import PlugIcon from "@lucide/svelte/icons/plug";
import RocketIcon from "@lucide/svelte/icons/rocket";
import SearchIcon from "@lucide/svelte/icons/search";
import SettingsIcon from "@lucide/svelte/icons/settings";
import ShieldIcon from "@lucide/svelte/icons/shield";
import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
import UsersIcon from "@lucide/svelte/icons/users";

export const docIcons: Record<string, Component> = {
	"book-open": BookOpenIcon,
	"circle-help": CircleHelpIcon,
	clock: ClockIcon,
	compass: CompassIcon,
	database: DatabaseIcon,
	"file-text": FileTextIcon,
	"flask-conical": FlaskConicalIcon,
	folder: FolderIcon,
	history: HistoryIcon,
	info: InfoIcon,
	"key-round": KeyRoundIcon,
	lightbulb: LightbulbIcon,
	link: LinkIcon,
	lock: LockIcon,
	package: PackageIcon,
	pencil: PencilIcon,
	plug: PlugIcon,
	rocket: RocketIcon,
	search: SearchIcon,
	settings: SettingsIcon,
	shield: ShieldIcon,
	"triangle-alert": TriangleAlertIcon,
	users: UsersIcon,
};

export function docIcon(name: string | undefined, fallback = "file-text"): Component {
	return (name && docIcons[name]) || docIcons[fallback];
}
