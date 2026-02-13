import { Search, Bell, Sun, Menu } from 'lucide-react';

interface DashboardHeaderProps {
    user?: { name: string; initials: string };
    toggleSidebar: () => void;
}

export function DashboardHeader({ user, toggleSidebar }: DashboardHeaderProps) {
    return (
        <header className="h-16 border-b bg-card flex items-center justify-between px-4 lg:px-6 sticky top-0 z-40">
            <div className="flex items-center gap-4">
                <button
                    onClick={toggleSidebar}
                    className="p-2 hover:bg-muted rounded-lg lg:hidden"
                >
                    <Menu className="h-5 w-5" />
                </button>
                <div>
                    <h1 className="text-lg font-semibold">Dashboard Overview</h1>
                    <p className="text-xs text-muted-foreground hidden sm:block">Monitor your RAG pipeline and data sources</p>
                </div>
            </div>

            <div className="flex-1 max-w-xl mx-4 hidden md:block">
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input
                        type="text"
                        placeholder="Search..."
                        className="w-full pl-10 h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                    />
                </div>
            </div>

            <div className="flex items-center gap-3">
                <span className="hidden sm:inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300">
                    ✓ DEVELOPMENT
                </span>

                <button className="p-2 hover:bg-muted rounded-full relative">
                    <Bell className="h-5 w-5 text-muted-foreground" />
                    <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-red-500" />
                </button>

                <button className="p-2 hover:bg-muted rounded-full">
                    <Sun className="h-5 w-5 text-muted-foreground" />
                </button>

                <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center text-primary font-medium text-sm border border-primary/20">
                    {user?.initials || 'JD'}
                </div>
            </div>
        </header>
    );
}
