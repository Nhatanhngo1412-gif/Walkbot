import time
from .memory import MemoryReader
from offsets import (
    dwPlantedC4, m_pGameSceneNode, m_vecAbsOrigin,
    m_nBombSite, m_bBeingDefused, m_flDefuseLength, m_flTimerLength
)

class csBomb:
    BombPlantedTime = 0
    BombDefusedTime = 0
    
    @staticmethod
    def getC4BaseClass(pm, client):
        PlantedC4Class = pm.read_longlong(client + dwPlantedC4)
        return pm.read_longlong(PlantedC4Class) if PlantedC4Class else 0
    
    @staticmethod
    def getPositionWTS(pm, client, view_matrix, width, height):
        base_class = csBomb.getC4BaseClass(pm, client)
        if not base_class:
            return None
            
        C4Node = pm.read_longlong(base_class + m_pGameSceneNode)
        if not C4Node:
            return None
            
        c4_pos = (
            pm.read_float(C4Node + m_vecAbsOrigin),
            pm.read_float(C4Node + m_vecAbsOrigin + 0x4),
            pm.read_float(C4Node + m_vecAbsOrigin + 0x8)
        )
        
        # Hàm w2s sẽ được import ở nơi sử dụng, không nên phụ thuộc ở đây
        from .utils import w2s
        return w2s(view_matrix, *c4_pos, width, height)
    
    @staticmethod
    def getSite(pm, client):
        base_class = csBomb.getC4BaseClass(pm, client)
        if not base_class:
            return None
        Site = pm.read_int(base_class + m_nBombSite)
        return "A" if (Site != 1) else "B"
    
    @staticmethod
    def isPlanted(pm, client):
        BombIsPlanted = pm.read_bool(client + dwPlantedC4 - 0x8)
        if BombIsPlanted:
            if csBomb.BombPlantedTime == 0:
                csBomb.BombPlantedTime = time.time()
        else:
            csBomb.BombPlantedTime = 0
        return BombIsPlanted
    
    @staticmethod
    def isBeingDefused(pm, client):
        base_class = csBomb.getC4BaseClass(pm, client)
        if not base_class:
            return False
        BombIsDefused = pm.read_bool(base_class + m_bBeingDefused)
        if BombIsDefused:
            if csBomb.BombDefusedTime == 0:
                csBomb.BombDefusedTime = time.time()
        else:
            csBomb.BombDefusedTime = 0
        return BombIsDefused
    
    @staticmethod
    def getDefuseLength(pm, client):
        base_class = csBomb.getC4BaseClass(pm, client)
        if not base_class:
            return 0.0
        return pm.read_float(base_class + m_flDefuseLength)
    
    @staticmethod
    def getTimerLength(pm, client):
        base_class = csBomb.getC4BaseClass(pm, client)
        if not base_class:
            return 0.0
        return pm.read_float(base_class + m_flTimerLength)
    
    @staticmethod
    def getBombTime(pm, client):
        if csBomb.BombPlantedTime == 0:
            return 0.0
        timer_length = csBomb.getTimerLength(pm, client)
        bomb_time = timer_length - (time.time() - csBomb.BombPlantedTime)
        return max(0.0, bomb_time)
    
    @staticmethod
    def getDefuseTime(pm, client):
        if not csBomb.isBeingDefused(pm, client) or csBomb.BombDefusedTime == 0:
            return 0.0
        defuse_length = csBomb.getDefuseLength(pm, client)
        defuse_time = defuse_length - (time.time() - csBomb.BombDefusedTime)
        return max(0.0, defuse_time)