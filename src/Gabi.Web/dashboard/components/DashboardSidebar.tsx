
import {
    LayoutDashboard,
    Database,
    Activity,
    Settings,
    LogOut,
    Search,
    ChevronLeft,
    ChevronRight
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { useNavigate, useLocation } from 'react-router-dom';

interface DashboardSidebarProps {
    isOpen: boolean;
    onToggle: () => void;
    onLogout: () => void;
}

export function DashboardSidebar({ isOpen, onToggle, onLogout }: DashboardSidebarProps) {
    const navigate = useNavigate();
    const location = useLocation();

    const navItems = [
        { icon: LayoutDashboard, label: 'Dashboard', path: '/dashboard' },
        { icon: Database, label: 'Sources', path: '/dashboard/sources' },
        { icon: Activity, label: 'Pipeline', path: '/dashboard/pipeline' },
        { icon: Search, label: 'Safra Details', path: '/dashboard/safra' },
        { icon: Settings, label: 'Settings', path: '/dashboard/settings' },
    ];

    return (
        <aside
            className={cn(
                "fixed inset-y-0 left-0 z-50 bg-card border-r transition-all duration-300 flex flex-col",
                isOpen ? "w-64" : "w-16",
                // Mobile behavior: hidden by default, or handled via separate mobile menu?
                // For now, assume desktop-first collapsible, on mobile it might overlay or be handled by parent state
                "hidden lg:flex"
            )}
        >
            <div className="h-16 flex items-center px-4 border-b justify-between">
                <div className={cn("flex items-center gap-2", !isOpen && "justify-center w-full")}>
                    <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center flex-shrink-0">
                        <Database className="h-5 w-5 text-primary-foreground" />
                    </div>
                    {isOpen && <span className="font-semibold truncate">GABI</span>}
                </div>
                {isOpen && (
                    <button onClick={onToggle} className="p-1 hover:bg-muted rounded text-muted-foreground">
                        <ChevronLeft className="h-4 w-4" />
                    </button>
                )}
            </div>

            <div className="flex-1 py-4 flex flex-col gap-1 px-2">
                {navItems.map((item) => {
                    const isActive = location.pathname === item.path || (item.path === '/dashboard' && location.pathname === '/dashboard/');
                    return (
                        <button
                            key={item.path}
                            onClick={() => navigate(item.path)}
                            className={cn(
                                "flex items-center gap-3 px-3 py-2 rounded-lg transition-colors group relative",
                                isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                                !isOpen && "justify-center"
                            )}
                            title={!isOpen ? item.label : undefined}
                        >
                            <item.icon className="h-5 w-5 flex-shrink-0" />
                            {isOpen && <span>{item.label}</span>}
                        </button>
                    );
                })}
            </div>

            <div className="p-4 border-t">
                {!isOpen && (
                    <button
                        onClick={onToggle}
                        className="w-full flex justify-center p-2 hover:bg-muted rounded-lg text-muted-foreground mb-2"
                    >
                        <ChevronRight className="h-4 w-4" />
                    </button>
                )}

                <button
                    onClick={onLogout}
                    className={cn(
                        "flex items-center gap-3 px-3 py-2 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground w-full group",
                        !isOpen && "justify-center"
                    )}
                    title={!isOpen ? "Logout" : undefined}
                >
                    <LogOut className="h-5 w-5 flex-shrink-0" />
                    {isOpen && <span>Logout</span>}
                </button>
            </div>
        </aside>
    );
}
