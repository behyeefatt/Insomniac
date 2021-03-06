from datetime import timedelta
from enum import Enum, unique

from insomniac.database_engine import *
from insomniac.utils import *

FILENAME_INTERACTED_USERS = "interacted_users.json"  # deprecated
FILENAME_SCRAPPED_USERS = "scrapped_users.json"  # deprecated
FILENAME_FILTERED_USERS = "filtered_users.json"  # deprecated
USER_LAST_INTERACTION = "last_interaction"
USER_INTERACTIONS_COUNT = "interactions_count"
USER_FILTERED_AT = "filtered_at"
USER_FOLLOWING_STATUS = "following_status"
USER_SCRAPPING_STATUS = "scrapping_status"

FILENAME_WHITELIST = "whitelist.txt"
FILENAME_BLACKLIST = "blacklist.txt"
FILENAME_TARGETS = "targets.txt"
FILENAME_LOADED_TARGETS = "targets_loaded.txt"
FILENAME_FOLLOWERS = "followers.txt"


STORAGE_ARGS = {
    "reinteract_after": {
        "help": "set a time (in hours) to wait before re-interact with an already interacted profile, disabled by default (won't interact again). "
                "It can be a number (e.g. 48) or a range (e.g. 50-80)",
        "metavar": "150"
    }
}


class Storage:
    database = None
    scrapping_databases = []
    reinteract_after = None
    whitelist = []
    blacklist = []
    account_followers = {}

    def __init__(self, my_username, args):
        self.database = get_database(my_username)

        if args.reinteract_after is not None:
            self.reinteract_after = get_value(args.reinteract_after, "Re-interact after {} hours", 168)

        scrape_for_account = args.__dict__.get('scrape_for_account', None)
        if my_username is None:
            print(COLOR_FAIL + "No username, thus the script won't get access to interacted users and sessions data" +
                  COLOR_ENDC)
            return

        if not os.path.exists(my_username):
            os.makedirs(my_username)

        # Whitelist and Blacklist
        whitelist_path = os.path.join(my_username, FILENAME_WHITELIST)
        if os.path.exists(whitelist_path):
            with open(whitelist_path, encoding="utf-8") as file:
                self.whitelist = [line.rstrip() for line in file]
        blacklist_path = os.path.join(my_username, FILENAME_BLACKLIST)
        if os.path.exists(blacklist_path):
            with open(blacklist_path, encoding="utf-8") as file:
                self.blacklist = [line.rstrip() for line in file]

        # Read targets from targets.txt
        targets_path = os.path.join(my_username, FILENAME_TARGETS)
        if os.path.exists(targets_path):
            with open(targets_path, 'r+', encoding="utf-8") as file_targets:
                targets = [line.rstrip() for line in file_targets]
                # Add targets to the database
                add_targets(self.database, targets, Provider.TARGETS_LIST)
                targets_loaded_path = os.path.join(my_username, FILENAME_LOADED_TARGETS)
                # Add targets to targets_loaded.txt
                with open(targets_loaded_path, 'a+', encoding="utf-8") as file_loaded_targets:
                    for target in targets:
                        file_loaded_targets.write(f"{target}\n")
                # Clear targets.txt
                file_targets.truncate(0)

        # Scraping
        if scrape_for_account is not None:
            for acc in scrape_for_account:
                self.scrapping_databases.append(get_database(acc))

            # TODO: implement 'dump-followers' feature or remove these lines
            # self.followers_path = os.path.join(scrape_for_account, FILENAME_FOLLOWERS)
            # if os.path.exists(self.followers_path):
            #     with open(self.followers_path, encoding="utf-8") as json_file:
            #         self.account_followers = json.load(json_file)

    def check_user_was_interacted(self, username):
        user = get_interacted_user(self.database, username)
        if self.reinteract_after is None:
            return user is not None and user[USER_INTERACTIONS_COUNT] > 0

        return self.check_user_was_interacted_recently(username, hours=self.reinteract_after)

    def check_user_was_interacted_recently(self, username, hours=72):
        user = get_interacted_user(self.database, username)
        if user is None or user[USER_INTERACTIONS_COUNT] == 0:
            return False

        last_interaction = datetime.strptime(user[USER_LAST_INTERACTION], '%Y-%m-%d %H:%M:%S')
        return datetime.now() - last_interaction <= timedelta(hours=hours)

    def check_user_was_scrapped(self, username):
        user = get_scraped_user(self.database, username)
        return user is not None

    def check_user_was_filtered(self, username):
        user = get_filtered_user(self.database, username)
        return user is not None

    def get_following_status(self, username):
        user = get_interacted_user(self.database, username)
        return FollowingStatus.NONE if user is None else FollowingStatus[user[USER_FOLLOWING_STATUS].upper()]

    def add_interacted_user(self,
                            username,
                            last_interaction=datetime.now(),
                            followed=False,
                            unfollowed=False,
                            source=None,
                            interaction_type=None,
                            provider=Provider.UNKNOWN):
        following_status = FollowingStatus.NONE
        if followed:
            following_status = FollowingStatus.FOLLOWED
        if unfollowed:
            following_status = FollowingStatus.UNFOLLOWED
        update_interacted_users(self.database,
                                (username,),
                                (last_interaction,),
                                (following_status,),
                                (source,),
                                (interaction_type,),
                                (provider,))

    def add_scrapped_user(self, username, last_interaction=datetime.now(), success=False):
        scraping_status = ScrappingStatus.SCRAPED if success else ScrappingStatus.NOT_SCRAPED
        update_scraped_users(self.database, (username,), (last_interaction,), (scraping_status,))

    def add_filtered_user(self, username, filtered_at=datetime.now()):
        update_filtered_users(self.database, (username,), (filtered_at,))

    def add_target(self, username, source, interaction_type):
        """
        Add a target to the scrapping_database (it's a database of original account for which we are scrapping).
        """
        for scrapping_database in self.scrapping_databases:
            add_targets(scrapping_database, (username,), Provider.SCRAPING, source, interaction_type)

    def get_target(self):
        """
        Read and remove a target from the targets table.

        :return: a target or None if table is empty.
        """
        return get_target(self.database, [self.is_user_in_blacklist, self.check_user_was_filtered])

    def save_followers_for_today(self, followers_list, override=False):
        # TODO: implement 'dump-followers' feature or remove this function
        curr_day = str(datetime.date(datetime.now()))
        if curr_day in self.account_followers:
            if not override:
                return

        self.account_followers[curr_day] = followers_list

        if self.followers_path is not None:
            with open(self.followers_path, 'w', encoding="utf-8") as outfile:
                json.dump(self.account_followers, outfile, indent=4, sort_keys=False)

    def is_user_in_whitelist(self, username):
        return username in self.whitelist

    def is_user_in_blacklist(self, username):
        return username in self.blacklist


@unique
class FollowingStatus(Enum):
    NONE = 0
    FOLLOWED = 1
    UNFOLLOWED = 2


@unique
class ScrappingStatus(Enum):
    SCRAPED = 0
    NOT_SCRAPED = 1
